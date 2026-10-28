"""Durability, integrity, bounded storage and reconstructible host checkpoints."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
import sqlite3
import uuid

import pytest

from custom_components.adaptive_solar.core.archive import (
    ArchiveError, ArchiveJournal, ArchiveStore, canonical_bytes, validate_page,
)

NOW = datetime(2026, 10, 28, tzinfo=timezone.utc)


def journal(tmp_path, **options):
    return ArchiveJournal(tmp_path / "journal", **options)


def append(j, i=0, **kwargs):
    return j.append("weather_response", {"cell": i}, NOW + timedelta(minutes=i), **kwargs)


def test_journal_restart_idempotency_and_cursor(tmp_path):
    j = journal(tmp_path)
    first = append(j, event_id="original")
    assert append(j, event_id="original") == first
    with pytest.raises(ArchiveError, match="different content"):
        append(j, 1, event_id="original")
    p = j.page(limit=1)
    restarted = journal(tmp_path)
    second = append(restarted, 1)
    assert second["generation"] == first["generation"]
    assert restarted.page(p["next_cursor"])["events"] == [second]
    assert restarted.stats()["events"] == 2


def test_journal_overflow_explicit_gap_and_byte_page_limits(tmp_path):
    j = journal(tmp_path, max_events=2)
    events = [append(j, i) for i in range(5)]
    p = j.page(f'{events[0]["generation"]}:1')
    assert [e["sequence"] for e in p["events"]] == [4, 5]
    assert p["gap"] == {"reason": "retention_or_overflow", "from": 2, "to": 3}
    assert j.stats()["dropped_events"] == 3
    with pytest.raises(ArchiveError, match="cannot fit"):
        j.page(max_bytes=512)
    small = j.page(max_bytes=900)
    assert len(canonical_bytes(small)) <= 900
    with pytest.raises(ArchiveError):
        j.append("big", {"raw": "x" * 1024 * 1024}, NOW)
    assert j.stats()["next_sequence"] == 6


def test_journal_retention_prefix_and_generation_gap(tmp_path):
    j = journal(tmp_path, retention_hours=1)
    first = append(j)
    j.append("weather_response", {}, NOW + timedelta(hours=2))
    assert j.page()["gap"]["reason"] == "retention_or_overflow"
    unrelated = f"{uuid.uuid4()}:900"
    p = j.page(unrelated)
    assert p["gap"]["reason"] == "generation_changed"
    assert p["events"][0]["sequence"] == 2
    assert first["sequence"] == 1


def test_parallel_read_write_has_contiguous_consistent_pages(tmp_path):
    j = journal(tmp_path)
    def write(i):
        append(j, i)
        validate_page(j.page(limit=100))
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write, range(40)))
    assert [e["sequence"] for e in j.page()["events"]] == list(range(1, 41))
    assert journal(tmp_path).stats()["events"] == 40


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), object()])
def test_reject_invalid_payload_without_cursor_advance(tmp_path, bad):
    j = journal(tmp_path)
    with pytest.raises(ArchiveError):
        j.append("bad", {"value": bad}, NOW)
    assert j.stats()["next_sequence"] == 1


def test_host_retry_restart_and_rebuild(tmp_path):
    j = journal(tmp_path)
    append(j)
    store = ArchiveStore(tmp_path / "host")
    page = j.page()
    cursor = store.ingest_page("site", page)
    assert store.ingest_page("site", page) == cursor
    assert store.stats()["batches"] == 1
    restarted = ArchiveStore(tmp_path / "host")
    assert restarted.checkpoint("site") == cursor
    append(j, 1)
    second = j.page(cursor)
    restarted.ingest_page("site", second)
    before = list(restarted.iter_events())
    restarted.rebuild_index()
    assert list(restarted.iter_events()) == before
    assert restarted.checkpoint("site") == second["next_cursor"]
    assert len(before) == 2


def test_crash_after_original_before_index_recovers(tmp_path, monkeypatch):
    j = journal(tmp_path)
    append(j)
    store = ArchiveStore(tmp_path / "host")
    import custom_components.adaptive_solar.core.archive as module
    real = module._atomic
    def fail(*args):
        real(*args)
        raise OSError("simulated crash after durable original")
    monkeypatch.setattr(module, "_atomic", fail)
    with pytest.raises(OSError):
        store.ingest_page("site", j.page())
    assert store.checkpoint("site") is None
    assert len(list(store.originals.glob("*.json.gz"))) == 1
    monkeypatch.setattr(module, "_atomic", real)
    recovered = ArchiveStore(tmp_path / "host")
    assert recovered.checkpoint("site") == j.page()["next_cursor"]
    assert len(list(recovered.iter_events())) == 1


def test_disk_failure_before_original_does_not_advance(tmp_path, monkeypatch):
    import custom_components.adaptive_solar.core.archive as module
    j = journal(tmp_path)
    append(j)
    store = ArchiveStore(tmp_path / "host")
    def fail(*_):
        raise OSError("disk full")
    monkeypatch.setattr(module, "_atomic", fail)
    with pytest.raises(OSError):
        store.ingest_page("site", j.page())
    assert store.checkpoint("site") is None


def test_corrupt_original_rebuild_preserves_index(tmp_path):
    j = journal(tmp_path)
    append(j)
    store = ArchiveStore(tmp_path / "host")
    store.ingest_page("site", j.page())
    index = (store.root / "index.sqlite3").read_bytes()
    path = next(store.originals.glob("*.json.gz"))
    path.write_bytes(gzip.compress(b"{}"))
    with pytest.raises(ArchiveError, match="checksum"):
        store.rebuild_index()
    assert (store.root / "index.sqlite3").read_bytes() == index
    with pytest.raises(ArchiveError):
        store.verify()


@pytest.mark.parametrize("component", ["journal", "host"])
def test_unknown_or_corrupt_sqlite_not_overwritten(tmp_path, component):
    root = tmp_path / component
    root.mkdir()
    name = "journal.sqlite3" if component == "journal" else "index.sqlite3"
    path = root / name
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version=99")
        conn.execute("CREATE TABLE preserved(value)")
    before = path.read_bytes()
    with pytest.raises(ArchiveError, match="Unknown"):
        (ArchiveJournal if component == "journal" else ArchiveStore)(root)
    assert path.read_bytes() == before
    path.write_bytes(b"not sqlite")
    with pytest.raises(ArchiveError):
        (ArchiveJournal if component == "journal" else ArchiveStore)(root)
    assert path.read_bytes() == b"not sqlite"


def test_forged_events_and_conflicting_retry_do_not_advance(tmp_path):
    j = journal(tmp_path)
    append(j)
    store = ArchiveStore(tmp_path / "host")
    page = j.page()
    forged = json.loads(json.dumps(page))
    forged["events"][0]["payload"] = {"forged": 1}
    with pytest.raises(ArchiveError, match="checksum"):
        store.ingest_page("site", forged)
    assert store.checkpoint("site") is None
    store.ingest_page("site", page)
    event = forged["events"][0]
    event["sha256"] = hashlib.sha256(canonical_bytes({k: v for k, v in event.items() if k != "sha256"})).hexdigest()
    with pytest.raises(ArchiveError, match="Conflicting"):
        store.ingest_page("site", forged)


def test_generation_change_is_recorded_and_reconstructible(tmp_path):
    a, b = journal(tmp_path), ArchiveJournal(tmp_path / "another")
    append(a)
    append(b)
    store = ArchiveStore(tmp_path / "host")
    old = store.ingest_page("site", a.page())
    changed = b.page(old)
    assert changed["gap"]["reason"] == "generation_changed"
    current = store.ingest_page("site", changed)
    store.rebuild_index()
    assert store.checkpoint("site") == current
    assert len(list(store.iter_events())) == 2


def test_retention_calendar_months_pins_and_latest_checkpoint(tmp_path):
    j = journal(tmp_path)
    store = ArchiveStore(tmp_path / "host")
    append(j)
    first = store.ingest_page("site", j.page(), stored_at=datetime(2024, 2, 28, tzinfo=timezone.utc))
    store.pin("frozen")
    append(j, 1)
    second = store.ingest_page("site", j.page(first), stored_at=datetime(2024, 2, 28, tzinfo=timezone.utc))
    append(j, 2)
    last = store.ingest_page("site", j.page(second), stored_at=datetime(2024, 3, 1, tzinfo=timezone.utc))
    result = store.maintain(now=datetime(2026, 2, 28, 1, tzinfo=timezone.utc))
    assert result["removed_batches"] == 1
    assert store.stats()["events"] == 2
    store.rebuild_index()
    assert store.checkpoint("site") == last
    assert [e["payload"]["cell"] for e in store.iter_events()] == [0, 2]
    with pytest.raises(ArchiveError, match="already pinned"):
        store.pin("frozen")


def test_missing_original_aborts_and_corrupt_pins_abort_retention(tmp_path):
    j = journal(tmp_path)
    append(j)
    store = ArchiveStore(tmp_path / "host")
    store.ingest_page("site", j.page())
    (store.root / "pins.json").write_text('{"schema":99,"datasets":{}}')
    with pytest.raises(ArchiveError, match="pin manifest"):
        store.maintain()
    (store.root / "pins.json").unlink()
    next(store.originals.glob("*.json.gz")).unlink()
    with pytest.raises(ArchiveError, match="missing"):
        ArchiveStore(store.root)


def test_empty_pages_rebuild_checkpoints_and_capacity_dates(tmp_path):
    j = journal(tmp_path)
    store = ArchiveStore(tmp_path / "host")
    page = j.page()
    store.ingest_page("empty", page, stored_at=NOW)
    store.rebuild_index()
    assert store.checkpoint("empty") == page["next_cursor"]
    stats = store.stats(now=NOW + timedelta(days=91))
    assert stats["capacity_review_3_months_at"].startswith("2027-01-28")
    assert stats["capacity_review_6_months_at"].startswith("2027-04-28")


def test_frozen_dataset_membership_and_export_survive_later_ingest(tmp_path):
    j = journal(tmp_path)
    append(j)
    store = ArchiveStore(tmp_path / "host")
    cursor = store.ingest_page("site", j.page())
    store.pin("frozen")
    append(j, 1)
    store.ingest_page("site", j.page(cursor))
    assert len(list(store.iter_events(dataset="frozen"))) == 1
    manifest = store.export_dataset("frozen", tmp_path / "dataset")
    assert manifest["sources"]["site"]["events"] == 1
    restored = ArchiveStore(tmp_path / "dataset")
    assert list(restored.iter_events(dataset="frozen")) == list(store.iter_events(dataset="frozen"))
    with pytest.raises(ArchiveError, match="already exists"):
        store.export_dataset("frozen", tmp_path / "dataset")


def test_old_page_retry_does_not_regress_checkpoint(tmp_path):
    j = journal(tmp_path)
    append(j)
    store = ArchiveStore(tmp_path / "host")
    first_page = j.page()
    first = store.ingest_page("site", first_page)
    append(j, 1)
    latest = store.ingest_page("site", j.page(first))
    assert store.ingest_page("site", first_page) == latest
    assert store.checkpoint("site") == latest
    assert store.stats()["batches"] == 2


@pytest.mark.parametrize("operation", ["rebuild", "verify", "iterate", "maintain", "export"])
def test_missing_pinned_original_cannot_become_partial_dataset(tmp_path, operation):
    j = journal(tmp_path)
    store = ArchiveStore(tmp_path / "host")
    append(j)
    cursor = store.ingest_page("site", j.page())
    pinned = store.pin("frozen")
    append(j, 1)
    store.ingest_page("site", j.page(cursor))
    (store.originals / f"{pinned[0]}.json.gz").unlink()
    index_before = (store.root / "index.sqlite3").read_bytes()
    operations = {
        "rebuild": store.rebuild_index,
        "verify": store.verify,
        "iterate": lambda: list(store.iter_events(dataset="frozen")),
        "maintain": store.maintain,
        "export": lambda: store.export_dataset("frozen", tmp_path / "export"),
    }
    with pytest.raises(ArchiveError, match="missing"):
        operations[operation]()
    assert (store.root / "index.sqlite3").read_bytes() == index_before
    assert not (tmp_path / "export").exists()


def test_dataset_iteration_refuses_missing_index_membership(tmp_path):
    j = journal(tmp_path)
    store = ArchiveStore(tmp_path / "host")
    append(j)
    store.ingest_page("site", j.page())
    store.pin("frozen")
    with sqlite3.connect(store.root / "index.sqlite3") as conn:
        conn.execute("DELETE FROM batches")
    with pytest.raises(ArchiveError, match="indexed originals"):
        list(store.iter_events(dataset="frozen"))
    store.rebuild_index()
    assert len(list(store.iter_events(dataset="frozen"))) == 1


def test_bounded_journal_reuses_pages_without_vacuum_or_full_check_per_append(tmp_path, monkeypatch):
    import custom_components.adaptive_solar.core.archive as module
    j = journal(tmp_path, max_bytes=2 * 1024 * 1024, max_events=4)
    for i in range(4):
        j.append("state", {"chunk": "x" * 400000, "i": i}, NOW)
    statements = []
    real_connect = module._connect
    def traced_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        conn.set_trace_callback(statements.append)
        return conn
    monkeypatch.setattr(module, "_connect", traced_connect)
    before = j.stats()["disk_bytes"]
    for i in range(20):
        j.append("state", {"chunk": "y" * 400000, "i": i}, NOW)
    status = j.stats()
    assert status["events"] == 4
    assert status["event_bytes"] <= status["max_bytes"]
    assert status["disk_bytes"] <= before + 128 * 1024
    assert status["disk_bytes"] <= status["physical_limit_bytes"]
    assert not any("VACUUM" in statement.upper() for statement in statements)
    # Instrument the actual SQLite connection to include checks inside _connect.
    monkeypatch.setattr(module, "_connect", real_connect)
    checks = []
    real_sqlite_connect = module.sqlite3.connect
    def traced_sqlite(*args, **kwargs):
        conn = real_sqlite_connect(*args, **kwargs)
        conn.set_trace_callback(checks.append)
        return conn
    monkeypatch.setattr(module.sqlite3, "connect", traced_sqlite)
    j.append("state", {"chunk": "z" * 400000}, NOW)
    assert not any("QUICK_CHECK" in statement.upper() for statement in checks)
    assert j.verify()
    assert any("QUICK_CHECK" in statement.upper() for statement in checks)


@pytest.mark.parametrize("payload", [{"nested": {1: "bad"}}, {"array": [{False: 1}]}, {"nested": {1: "one", 2: "two", 10: "ten"}}])
def test_json_object_keys_must_round_trip_without_hash_changes(tmp_path, payload):
    j = journal(tmp_path)
    with pytest.raises(ArchiveError, match="keys must be strings"):
        j.append("state", payload, NOW)
    assert j.stats()["next_sequence"] == 1


def test_sqlite_physical_cap_enforced_and_reported(tmp_path):
    j = journal(tmp_path, max_bytes=4096, max_event_bytes=1024)
    append(j)
    status = j.stats()
    with j._db() as conn:
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]
        maximum_pages = conn.execute("PRAGMA max_page_count").fetchone()[0]
        assert maximum_pages * page_size <= status["physical_limit_bytes"]
        with pytest.raises(sqlite3.OperationalError, match="full"):
            conn.execute("INSERT INTO events VALUES(999,'oversized','now',zeroblob(?))",
                         (status["physical_limit_bytes"] + page_size,))
    assert j.stats()["disk_bytes"] <= status["physical_limit_bytes"]
    assert j.stats()["next_sequence"] == 2
    assert j.verify()


def test_batch_chunks_and_manifest_publish_atomically_and_retry(tmp_path):
    j = journal(tmp_path, max_events=3)
    append(j, 0)
    append(j, 1)
    batch = [("chunk", {"index": i}, NOW, f"chunk-{i}") for i in range(2)]
    batch.append(("manifest", {"chunks": ["chunk-0", "chunk-1"]}, NOW, "manifest"))
    published = j.append_many(batch)
    assert [event["sequence"] for event in published] == [3, 4, 5]
    assert [event["kind"] for event in j.page()["events"]] == ["chunk", "chunk", "manifest"]
    restarted = journal(tmp_path, max_events=3)
    assert restarted.append_many(batch) == published
    assert restarted.stats()["next_sequence"] == 6
    assert restarted.stats()["dropped_events"] == 2


def test_mid_batch_write_failure_rolls_back_pruning_rows_and_cursor(tmp_path, monkeypatch):
    import custom_components.adaptive_solar.core.archive as module
    j = journal(tmp_path, max_events=3)
    first, second = append(j, 0), append(j, 1)
    real_connect = module._connect
    def fail_on_second(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        conn.execute("CREATE TEMP TRIGGER abort_batch BEFORE INSERT ON events "
                     "WHEN NEW.event_id='fail' BEGIN SELECT RAISE(ABORT,'simulated write failure'); END")
        return conn
    monkeypatch.setattr(module, "_connect", fail_on_second)
    batch = [("chunk", {"i": i}, NOW, identifier) for i, identifier in enumerate(("first", "fail", "manifest"))]
    with pytest.raises(sqlite3.IntegrityError, match="simulated"):
        j.append_many(batch)
    assert j.page()["events"] == [first, second]
    assert j.stats()["next_sequence"] == 3
    assert j.stats()["dropped_events"] == 0
    monkeypatch.setattr(module, "_connect", real_connect)
    assert [event["sequence"] for event in j.append_many(batch)] == [3, 4, 5]


@pytest.mark.parametrize("mode", ["rows", "bytes", "last_invalid", "duplicate_ids", "mixed_retry"])
def test_invalid_batch_preserves_existing_rows_and_cursor(tmp_path, mode):
    j = journal(tmp_path, max_bytes=2048, max_events=3, max_event_bytes=2048)
    first = append(j, event_id="existing")
    if mode == "rows":
        batch = [("chunk", {}, NOW, f"new-{i}") for i in range(4)]
    elif mode == "bytes":
        batch = [("chunk", {"large": "x" * 850}, NOW, f"new-{i}") for i in range(2)]
    elif mode == "last_invalid":
        batch = [("chunk", {}, NOW, "new"), ("manifest", {"bad": float("nan")}, NOW, "manifest")]
    elif mode == "duplicate_ids":
        batch = [("chunk", {}, NOW, "same"), ("manifest", {}, NOW, "same")]
    else:
        batch = [("weather_response", {"cell": 0}, NOW, "existing"), ("manifest", {}, NOW, "new")]
    with pytest.raises(ArchiveError):
        j.append_many(batch)
    assert j.page()["events"] == [first]
    assert j.stats()["next_sequence"] == 2
    assert j.stats()["dropped_events"] == 0


@pytest.mark.parametrize("field", ["generation", "next_sequence", "dropped_events"])
def test_missing_journal_metadata_rejected_without_reinitialization(tmp_path, field):
    j = journal(tmp_path)
    append(j)
    path = j.root / "journal.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM metadata WHERE key=?", (field,))
    before = path.read_bytes()
    with pytest.raises(ArchiveError, match="Incomplete journal metadata"):
        journal(tmp_path)
    assert path.read_bytes() == before
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT value FROM metadata WHERE key=?", (field,)).fetchone() is None


@pytest.mark.parametrize("mode", ["next_sequence", "dropped_count", "generation_row", "sequence_row", "event_id_row", "receipt_row"])
def test_inconsistent_existing_journal_preserves_original_bytes(tmp_path, mode):
    j = journal(tmp_path)
    append(j)
    path = j.root / "journal.sqlite3"
    with sqlite3.connect(path) as conn:
        if mode == "next_sequence":
            conn.execute("UPDATE metadata SET value='1' WHERE key='next_sequence'")
        elif mode == "dropped_count":
            conn.execute("UPDATE metadata SET value='9' WHERE key='dropped_events'")
        elif mode == "generation_row":
            conn.execute("UPDATE metadata SET value=? WHERE key='generation'", (str(uuid.uuid4()),))
        elif mode == "sequence_row":
            conn.execute("UPDATE events SET sequence=5")
        elif mode == "event_id_row":
            conn.execute("UPDATE events SET event_id='different'")
        else:
            conn.execute("UPDATE events SET received_at='2020-01-01T00:00:00+00:00'")
    before = path.read_bytes()
    with pytest.raises(ArchiveError, match="Inconsistent journal"):
        journal(tmp_path)
    assert path.read_bytes() == before


def test_valid_pruned_journal_metadata_survives_restart(tmp_path):
    j = journal(tmp_path, max_events=2)
    for i in range(6):
        append(j, i)
    restored = journal(tmp_path, max_events=2)
    assert restored.verify()
    assert restored.stats()["dropped_events"] == 4
    assert restored.stats()["next_sequence"] == 7
    assert [event["sequence"] for event in restored.page()["events"]] == [5, 6]
