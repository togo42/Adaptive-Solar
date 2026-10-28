"""Indexed dependency reads retain source, generation, pin and original integrity."""
from datetime import UTC, datetime, timedelta
import json
import sqlite3

import pytest

from custom_components.adaptive_solar.core.archive import ArchiveError, ArchiveJournal, ArchiveStore

NOW = datetime(2026, 10, 28, tzinfo=UTC)


def setup_archive(tmp_path):
    journal = ArchiveJournal(tmp_path / "journal")
    store = ArchiveStore(tmp_path / "archive")
    events = []
    for index in range(3):
        event = journal.append("part", {"index": index}, NOW + timedelta(seconds=index))
        store.ingest_page("ha", journal.page(store.checkpoint("ha")))
        events.append(event)
        if index == 0:
            store.pin("first")
    return journal, store, events


def test_resolver_reads_only_referenced_originals_in_requested_order(tmp_path, monkeypatch):
    _, store, events = setup_archive(tmp_path)
    reads = []
    original = store._read_original
    def read(path):
        reads.append(path)
        return original(path)
    monkeypatch.setattr(store, "_read_original", read)
    selected = [events[2], events[0]]
    result = store.resolve_events([event["event_id"] for event in selected], source="ha",
                                  generation=events[0]["generation"])
    assert result == [{"source": "ha", **event} for event in selected]
    assert len(reads) == 2
    assert store.resolve_events([events[0]["event_id"]], source="ha",
                                generation=events[0]["generation"], dataset="first")[0]["event_id"] == events[0]["event_id"]


@pytest.mark.parametrize("mode", ["outside_pin", "missing", "wrong_source", "wrong_generation", "duplicate"])
def test_incomplete_or_cross_boundary_reference_fails_closed(tmp_path, mode):
    _, store, events = setup_archive(tmp_path)
    options = {"source": "ha", "generation": events[0]["generation"]}
    identifiers = [events[2]["event_id"]]
    if mode == "outside_pin":
        options["dataset"] = "first"
    elif mode == "missing":
        identifiers = ["not-present"]
    elif mode == "wrong_source":
        options["source"] = "different"
    elif mode == "wrong_generation":
        options["generation"] = "00000000-0000-0000-0000-000000000001"
    else:
        identifiers *= 2
    with pytest.raises(ArchiveError):
        store.resolve_events(identifiers, **options)


@pytest.mark.parametrize("corruption", ["digest", "ambiguous_id"])
def test_original_remains_authoritative_over_corrupted_lookup_index(tmp_path, corruption):
    _, store, events = setup_archive(tmp_path)
    with sqlite3.connect(store.root / "index.sqlite3") as conn:
        if corruption == "digest":
            conn.execute("UPDATE events SET sha256=? WHERE sequence=1", ("0" * 64,))
        else:
            conn.execute("UPDATE events SET event_id=? WHERE sequence=2", (events[0]["event_id"],))
    with pytest.raises(ArchiveError, match="disagrees|Ambiguous"):
        store.resolve_events([events[0]["event_id"]], source="ha", generation=events[0]["generation"])


def test_lookup_handles_bounded_sql_batches_and_rebuilt_index(tmp_path):
    journal = ArchiveJournal(tmp_path / "journal")
    events = journal.append_many([("part", {"index": i}, NOW, f"part-{i}") for i in range(220)])
    store = ArchiveStore(tmp_path / "archive")
    store.ingest_page("ha", journal.page(limit=300))
    store.rebuild_index()
    result = store.resolve_events([event["event_id"] for event in events], source="ha",
                                  generation=events[0]["generation"])
    assert [event["payload"]["index"] for event in result] == list(range(220))
    with pytest.raises(ArchiveError, match="1024"):
        store.resolve_events([f"id-{i}" for i in range(1025)], source="ha", generation=events[0]["generation"])


def test_reader_checks_full_pin_only_at_entry_and_completion(tmp_path, monkeypatch):
    _, store, events = setup_archive(tmp_path)
    calls = []
    original = store._validate_pins
    def validate(pins=None):
        calls.append(pins)
        return original(pins)
    monkeypatch.setattr(store, "_validate_pins", validate)
    with store.reference_reader(source="ha", generation=events[0]["generation"], dataset="first") as resolve:
        for _ in range(10):
            assert resolve([events[0]["event_id"]])[0]["event_id"] == events[0]["event_id"]
        assert len(calls) == 1
    assert len(calls) == 2
    with pytest.raises(ArchiveError, match="closed"):
        resolve([events[0]["event_id"]])


@pytest.mark.parametrize("change", ["manifest", "unused_original"])
def test_reader_rejects_pin_drift_before_result_publication(tmp_path, change):
    _, store, events = setup_archive(tmp_path)
    store.pin("all")
    with pytest.raises(ArchiveError, match="changed|missing"):
        with store.reference_reader(source="ha", generation=events[0]["generation"], dataset="all") as resolve:
            resolve([events[0]["event_id"]])
            path = store.root / "pins.json"
            pins = json.loads(path.read_text())
            if change == "manifest":
                pins["datasets"]["all"].pop()
                path.write_text(json.dumps(pins))
            else:
                digest = pins["datasets"]["all"][-1]
                store._original_path(digest).unlink()
