"""Lossless actual/reference history and availability survive offline archival."""
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from custom_components.adaptive_solar.core.archive import ArchiveError, ArchiveJournal, ArchiveStore
from scripts import archive_observations as subject
from scripts import capture_actuals

NOW = datetime(2026, 10, 27, 12, 15, tzinfo=UTC)


def capture(size=1):
    return {"capture_id": "synthetic-capture", "retrieved_at": NOW.isoformat(), "data": "ä" * size}


def ingest(journal, store, source="test"):
    cursor = store.checkpoint(source)
    while True:
        page = journal.page(cursor)
        next_cursor = store.ingest_page(source, page, stored_at=NOW)
        if not page["events"] or cursor == next_cursor:
            return
        cursor = next_cursor


@pytest.mark.parametrize("day", [datetime(2026, 3, 29, 3, 5, tzinfo=ZoneInfo("Europe/Berlin")),
                                  datetime(2026, 10, 25, 3, 5, tzinfo=ZoneInfo("Europe/Berlin"))])
def test_closed_hours_and_lag_on_both_dst_changes(day):
    start, end = subject.actual_window(day, lookback_hours=48)
    assert end <= day.astimezone(UTC) - timedelta(minutes=10)
    assert end.minute == 0 and end.second == 0
    assert end - start == timedelta(hours=48)
    assert start.tzinfo is UTC and end.tzinfo is UTC


def test_lossless_large_unicode_capture_survives_reopen_and_frozen_dataset(tmp_path):
    journal = ArchiveJournal(tmp_path / "journal")
    store = ArchiveStore(tmp_path / "store")
    original = capture(600000)
    subject.append_capture(journal, "references", original)
    ingest(journal, store)
    store.pin("frozen")
    original["data"] = "changed after archival"
    reread = list(subject.captures_from_archive(ArchiveStore(store.root), source="test", kind="references", dataset="frozen"))
    assert len(reread) == 1 and reread[0]["data"] == "ä" * 600000


@pytest.mark.parametrize("empty", [False, True])
@pytest.mark.parametrize("location", ["root", "originals", "prefix", "alias", "lexical_escape"])
def test_observation_export_refuses_archive_targets_and_preserves_further_collection(tmp_path, empty, location):
    from scripts import archive

    journal, store = ArchiveJournal(tmp_path / "journal"), ArchiveStore(tmp_path / "store")
    if not empty:
        subject.append_capture(journal, "actuals", capture())
        ingest(journal, store)
    if location == "root":
        target = store.root / "capture.jsonl"
    elif location == "originals":
        target = store.originals / "export.json.gz"
    elif location == "prefix":
        parent = store.originals / "ab"
        parent.mkdir(exist_ok=True)
        target = parent / "export.json.gz"
    elif location == "alias":
        parent = tmp_path / "alias"
        parent.symlink_to(store.originals, target_is_directory=True)
        target = parent / "export.json.gz"
    else:
        outside = tmp_path / "outside"
        outside.mkdir()
        parent = store.root / "escape"
        parent.symlink_to(outside, target_is_directory=True)
        target = parent / "export.json.gz"
    before = {str(path.relative_to(store.root)): path.read_bytes() for path in store.originals.rglob("*.json.gz")}
    assert archive.main(["--root", str(store.root), "export-observations", "--source", "test", "--kind", "actuals",
                         "--output", str(target)]) == 1
    assert not target.exists()
    assert {str(path.relative_to(store.root)): path.read_bytes() for path in store.originals.rglob("*.json.gz")} == before
    reopened = ArchiveStore(store.root)
    assert reopened.verify()
    subject.append_capture(journal, "actuals", {**capture(), "capture_id": "next-capture"})
    ingest(journal, reopened)
    assert reopened.verify()
    assert len(list(subject.captures_from_archive(reopened, source="test", kind="actuals"))) == 1 + int(not empty)


def test_observation_export_rejects_internal_target_before_opening_archive(tmp_path, monkeypatch):
    from scripts import archive

    root = tmp_path / "never-opened"
    monkeypatch.setattr(archive, "ArchiveStore", lambda *_: pytest.fail("archive opened before target validation"))
    assert archive.main(["--root", str(root), "export-observations", "--source", "test", "--kind", "actuals",
                         "--output", str(root / "originals/export.json.gz")]) == 1
    assert not root.exists()


def test_observation_export_rechecks_parent_before_publication(tmp_path, monkeypatch):
    from scripts import archive

    store = ArchiveStore(tmp_path / "store")
    parent = tmp_path / "output"
    parent.mkdir()
    target = parent / "export.json.gz"

    def redirected_capture(*_, **__):
        yield capture()
        parent.rename(tmp_path / "old-output")
        parent.symlink_to(store.originals, target_is_directory=True)
    monkeypatch.setattr(subject, "captures_from_archive", redirected_capture)
    monkeypatch.setattr(archive.os, "link", lambda *_: pytest.fail("publication attempted into source archive"))
    assert archive.main(["--root", str(store.root), "export-observations", "--source", "test", "--kind", "actuals",
                         "--output", str(target)]) == 1
    assert not target.exists() and ArchiveStore(store.root).verify()


def test_observation_export_rechecks_parent_before_temporary_creation(tmp_path, monkeypatch):
    from scripts import archive

    store = ArchiveStore(tmp_path / "store")
    parent = tmp_path / "output"
    parent.mkdir()

    def open_then_redirect(root):
        result = ArchiveStore(root)
        parent.rename(tmp_path / "old-output")
        parent.symlink_to(store.originals, target_is_directory=True)
        return result
    monkeypatch.setattr(archive, "ArchiveStore", open_then_redirect)
    monkeypatch.setattr(archive.tempfile, "mkstemp", lambda **_: pytest.fail("temporary created inside source archive"))
    assert archive.main(["--root", str(store.root), "export-observations", "--source", "test", "--kind", "actuals",
                         "--output", str(parent / "export.json.gz")]) == 1
    assert ArchiveStore(store.root).verify()


@pytest.mark.parametrize("empty", [False, True])
@pytest.mark.parametrize("alias_parent", [False, True])
def test_observation_export_external_jsonl_roundtrip_never_overwrites(tmp_path, empty, alias_parent):
    import json
    from scripts import archive

    journal, store = ArchiveJournal(tmp_path / "journal"), ArchiveStore(tmp_path / "store")
    if not empty:
        subject.append_capture(journal, "actuals", capture())
        ingest(journal, store)
    parent = tmp_path / "output"
    parent.mkdir()
    if alias_parent:
        alias = tmp_path / "outside-alias"
        alias.symlink_to(parent, target_is_directory=True)
        parent = alias
    target = parent / "capture.jsonl"
    args = ["--root", str(store.root), "export-observations", "--source", "test", "--kind", "actuals",
            "--output", str(target)]
    assert archive.main(args) == 0
    before = target.read_bytes()
    assert [json.loads(line) for line in target.read_text().splitlines()] == ([] if empty else [capture()])
    assert archive.main(args) == 1 and target.read_bytes() == before
    assert ArchiveStore(store.root).verify()


def test_missing_chunk_never_becomes_partial_usable_capture(tmp_path):
    journal = ArchiveJournal(tmp_path / "journal", max_events=2)
    store = ArchiveStore(tmp_path / "store")
    subject.append_capture(journal, "actuals", capture())
    journal.append("unrelated", {}, NOW)
    ingest(journal, store)
    with pytest.raises(ArchiveError, match="missing chunks"):
        list(subject.captures_from_archive(store, source="test", kind="actuals"))


def test_failed_capture_batch_leaves_no_orphan_and_next_export_succeeds(tmp_path):
    import sqlite3

    journal = ArchiveJournal(tmp_path / "journal")
    # Abort exactly at the manifest, after a chunk INSERT in the same transaction.
    with sqlite3.connect(journal.root / "journal.sqlite3") as db:
        db.execute("""CREATE TRIGGER fail_manifest BEFORE INSERT ON events
                      WHEN json_extract(CAST(NEW.raw AS TEXT), '$.kind') = 'observation_capture'
                      BEGIN SELECT RAISE(ABORT, 'injected manifest failure'); END""")
    with pytest.raises((ArchiveError, sqlite3.DatabaseError)):
        subject.append_capture(journal, "references", capture())
    assert journal.page()["events"] == []
    with sqlite3.connect(journal.root / "journal.sqlite3") as db:
        db.execute("DROP TRIGGER fail_manifest")
    original = {**capture(), "capture_id": "next-complete"}
    subject.append_capture(journal, "references", original)
    store = ArchiveStore(tmp_path / "store")
    ingest(journal, store)
    assert list(subject.captures_from_archive(store, source="test", kind="references")) == [original]


def raw_actual():
    start, end = subject.actual_window(NOW, lookback_hours=1)
    mapping = ({"inverter_id": "roof", "statistic_ids": ["sensor.energy"]},)
    metadata = [{"statistic_id": "sensor.energy", "has_sum": True, "unit_class": "energy", "statistics_unit_of_measurement": "kWh"}]
    stats = {"sensor.energy": [{"start": start.timestamp() * 1000, "end": end.timestamp() * 1000, "change": 2.0}]}
    return mapping, capture_actuals.build_raw_capture(metadata, stats, mapping, start, end, NOW)


async def test_unknown_quality_preserves_raw_but_does_not_invent_training_truth(tmp_path, monkeypatch):
    mapping, raw = raw_actual()
    monkeypatch.setattr(subject.capture_actuals, "capture_actuals", AsyncMock(return_value=raw))
    store = ArchiveStore(tmp_path / "store")
    result = await subject.archive_observations(store, source="ha", ha_url="http://example.invalid", token="test-token",
                                               actual_mappings=mapping, now=NOW, lookback_hours=1)
    assert result["complete"]
    assert result["streams"]["actuals"]["complete"]
    assert result["streams"]["actuals"]["current_capture_confirmed"]
    assert result["streams"]["actuals"]["accepted_intervals"] == 0
    captures = list(subject.captures_from_archive(store, source="ha:actuals", kind="actuals"))
    assert captures[0]["raw"] == raw["raw"]
    assert "missing_quality_evidence" in captures[0]["normalization"]["excluded"][0]["reasons"]


async def test_invalid_quality_retains_original_and_marks_failure(tmp_path, monkeypatch):
    mapping, raw = raw_actual()
    monkeypatch.setattr(subject.capture_actuals, "capture_actuals", AsyncMock(return_value=raw))
    store = ArchiveStore(tmp_path / "store")
    result = await subject.archive_observations(store, source="ha", ha_url="http://example.invalid", token="test-token",
                                               actual_mappings=mapping, quality={"invalid": True}, now=NOW)
    assert not result["complete"]
    saved = list(subject.captures_from_archive(store, source="ha:actuals", kind="actuals"))[0]
    assert saved["raw"] == raw["raw"] and saved["normalization_error"] == "invalid_quality_or_raw"


async def test_actual_outage_does_not_erase_reference_and_late_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(subject.capture_actuals, "capture_actuals", AsyncMock(side_effect=capture_actuals.CaptureError("unavailable")))
    raw = {**capture(), "cutoff_check": {"late_group_count": 1}}
    monkeypatch.setattr(subject.capture_ha, "capture_forecasts", AsyncMock(return_value=raw))
    store = ArchiveStore(tmp_path / "store")
    result = await subject.archive_observations(store, source="ha", ha_url="http://example.invalid", token="test-token",
                                               actual_mappings=[{}], reference_mappings=[{}], now=NOW)
    assert not result["complete"]
    assert result["streams"]["actuals"]["status"] == "failed"
    assert result["streams"]["references"]["status"] == "late"
    assert list(subject.captures_from_archive(store, source="ha:references", kind="references")) == [raw]


async def test_credential_echo_is_never_stored(tmp_path, monkeypatch):
    raw = {**capture(), "data": "secret-test-token"}
    monkeypatch.setattr(subject.capture_ha, "capture_forecasts", AsyncMock(return_value=raw))
    store = ArchiveStore(tmp_path / "store")
    result = await subject.archive_observations(store, source="ha", ha_url="http://example.invalid", token="secret-test-token",
                                               reference_mappings=[{}])
    assert not result["complete"]
    assert list(store.iter_events(source="ha:references")) == []


@pytest.mark.parametrize("phase", ["normal", "recovery", "final"])
def test_local_collection_completion_reaches_observation_cli_and_host_exit(tmp_path, monkeypatch, capsys, phase):
    import json
    import subprocess
    from contextlib import redirect_stdout, redirect_stderr
    from io import StringIO
    from types import SimpleNamespace
    from scripts import archive_host as host

    monkeypatch.setattr(subject, "ROOT", tmp_path)
    monkeypatch.setattr(host, "ROOT", tmp_path)
    (tmp_path / "data").mkdir()
    refs = tmp_path / "data/references.json"
    refs.write_text(json.dumps({"mappings": [{"inverter_id": "roof", "source": "helios", "entry_ids": ["entry"]}]}))
    raw = {**capture(), "cutoff_check": {"late_group_count": 0}}
    capture_mock = AsyncMock(return_value=raw)
    monkeypatch.setattr(subject.capture_ha, "capture_forecasts", capture_mock)
    normal_collect = subject.collect
    calls = 0
    async def collection(store, source, fetch, **kwargs):
        nonlocal calls
        calls += 1
        # Exercise the real local journal callback and durable page commits.
        result = await normal_collect(store, source, fetch, **kwargs)
        if (phase == "recovery" and calls == 1) or (phase == "final" and calls == 2):
            result.update(complete=False, collection_end_confirmed=False, page_limit_reached=True,
                          failures=["incomplete_collection"])
        return result
    monkeypatch.setattr(subject, "collect", collection)
    config = {"archive": "data/archive", "entries": [], "weather_source": "weather",
              "observations_source": "measurements", "reference_config": "data/references.json",
              "min_free_bytes": 20, "operation_reserve_bytes": 10, "max_archive_bytes": 1000000,
              "min_free_percent": 15}
    cfg = tmp_path / "data/host.json"
    cfg.write_text(json.dumps(config))
    monkeypatch.setattr(host.shutil, "disk_usage", lambda _: SimpleNamespace(free=10000, total=10000))
    results = []
    def process(command, **_):
        if command[-1] == "stats":
            values = {key: 0 for key in ("batches", "events", "compressed_bytes", "index_bytes",
                "observation_days", "compressed_bytes_per_day", "projected_24_month_compressed_bytes")}
            return subprocess.CompletedProcess(command, 0, json.dumps(values), "")
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = subject.main(command[2:])
        results.append(json.loads(stdout.getvalue()))
        return subprocess.CompletedProcess(command, code, stdout.getvalue(), stderr.getvalue())
    monkeypatch.setattr(host.subprocess, "run", process)
    code = host.main(["observations", "--config", str(cfg)])
    report = json.loads(capsys.readouterr().out)
    assert (code == 0) == report["complete"] == results[0]["complete"] == (phase == "normal")
    stream = results[0]["streams"]["references"]
    assert stream["current_capture_confirmed"] == (phase == "normal")
    if phase == "recovery":
        assert stream["status"] == "recovery_incomplete"
        capture_mock.assert_not_awaited()
    elif phase == "final":
        assert stream["status"] == "collection_incomplete"


@pytest.fixture
def backend_cli_case(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    monkeypatch.setattr(subject, "ROOT", tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    actual, bindings, manifest = (data / name for name in ("actuals.json", "bindings.json", "backend.json"))
    actual.write_text(json.dumps({"mappings": [{"inverter_id": "roof", "statistic_ids": ["sensor.energy"]}]}))
    bindings.write_text(json.dumps({"schema": "adaptive-solar-actual-quality-bindings-v2", "bindings": []}))
    manifest.write_text("{}")
    return SimpleNamespace(base=["--archive", str(data / "archive"), "--source", "measurements"],
        actual=["--actual-config", str(actual)], bindings=["--quality-bindings", str(bindings)],
        native=["--quality-backend-manifest", str(manifest), "--quality-backend-manifest-sha256", "a" * 64],
        manifest=manifest)


def test_observation_cli_default_does_not_import_native_backend(backend_cli_case, monkeypatch, capsys):
    import builtins
    import json

    original_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "scripts.native_quality_backend" or name == "scripts" and "native_quality_backend" in (fromlist or ()):
            pytest.fail("Default observation CLI must not import the native backend")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    store = object()
    monkeypatch.setattr(subject, "ArchiveStore", lambda path: store)
    worker = AsyncMock(return_value={"complete": True})
    monkeypatch.setattr(subject, "archive_observations", worker)
    assert subject.main(backend_cli_case.base + backend_cli_case.actual) == 0
    assert worker.call_args.args == (store,)
    assert worker.call_args.kwargs["quality_backend"] is None
    assert "quality_backend" not in json.loads(capsys.readouterr().out)


@pytest.mark.parametrize("missing", ["manifest", "pin", "actual", "bindings"])
def test_native_cli_requires_complete_activation_before_archive_creation(backend_cli_case, monkeypatch, missing):
    arguments = backend_cli_case.base + backend_cli_case.actual + backend_cli_case.bindings + backend_cli_case.native
    flag = {"manifest": "--quality-backend-manifest", "pin": "--quality-backend-manifest-sha256",
            "actual": "--actual-config", "bindings": "--quality-bindings"}[missing]
    index = arguments.index(flag)
    del arguments[index:index + 2]
    monkeypatch.setattr(subject, "ArchiveStore", lambda *args: pytest.fail("Invalid activation must not create an archive"))
    with pytest.raises(SystemExit) as failure:
        subject.main(arguments)
    assert failure.value.code == 2


def test_invalid_requested_backend_fails_before_archive_creation_and_hides_details(backend_cli_case, monkeypatch, capsys):
    from scripts import native_quality_backend

    calls = []

    def invalid_manifest(path, pin):
        calls.append((path, pin))
        raise ValueError("private-token-and-installation-path")

    monkeypatch.setattr(native_quality_backend, "load_backend", invalid_manifest)
    monkeypatch.setattr(subject, "ArchiveStore", lambda *args: pytest.fail("Invalid backend must fail before database initialization"))
    assert subject.main(backend_cli_case.base + backend_cli_case.actual + backend_cli_case.bindings + backend_cli_case.native) == 2
    assert calls == [(backend_cli_case.manifest, "a" * 64)]
    assert "private-token" not in capsys.readouterr().err


def test_native_cli_loads_before_archive_creation_and_forwards_exact_backend(backend_cli_case, monkeypatch, capsys):
    import json
    from types import SimpleNamespace
    from scripts import native_quality_backend

    order, backend, store = [], SimpleNamespace(stats={"closed": True}), object()

    def load_backend(path, pin):
        assert path == backend_cli_case.manifest and pin == "a" * 64
        order.append("load")
        return backend

    def open_store(path):
        order.append("archive")
        return store

    async def observe(actual_store, **options):
        order.append("capture")
        assert actual_store is store and options["quality_backend"] is backend
        assert options["quality_bindings"]["schema"] == "adaptive-solar-actual-quality-bindings-v2"
        return {"complete": True, "quality_backend": backend.stats}

    monkeypatch.setattr(native_quality_backend, "load_backend", load_backend)
    monkeypatch.setattr(subject, "ArchiveStore", open_store)
    monkeypatch.setattr(subject, "archive_observations", observe)
    assert subject.main(backend_cli_case.base + backend_cli_case.actual + backend_cli_case.bindings + backend_cli_case.native) == 0
    assert order == ["load", "archive", "capture"]
    assert json.loads(capsys.readouterr().out)["quality_backend"] == backend.stats


@pytest.mark.parametrize("actual,bindings", [(False, True), (True, False)])
async def test_backend_object_requires_actual_mapping_and_continuous_policy_before_journal(tmp_path, monkeypatch, actual, bindings):
    monkeypatch.setattr(subject, "ArchiveJournal", lambda *args: pytest.fail("Invalid activation must not create a journal"))
    store = ArchiveStore(tmp_path / "store")
    with pytest.raises(ArchiveError, match="requires"):
        await subject.archive_observations(store, source="test", ha_url="", token="",
            actual_mappings=[{}] if actual else None, reference_mappings=[{}],
            quality_bindings={"bindings": []} if bindings else None, quality_backend=object())


async def test_backend_status_stays_outside_capture_and_raw_and_quality_bytes_match_default(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from copy import deepcopy
    from freezegun import freeze_time
    from custom_components.adaptive_solar.core.archive import canonical_bytes
    from tests.test_capture_actuals import capture as recorder_capture
    from tests.test_continuous_quality import continuous_case, store_case

    case = continuous_case()
    store = store_case(tmp_path, case)
    raw = recorder_capture(start=case[3], end=case[4], received=case[-1])
    before = deepcopy(raw)
    monkeypatch.setattr(capture_actuals, "capture_actuals", AsyncMock(return_value=raw))

    class Backend:
        calls = 0
        stats = None

        @contextmanager
        def bind(self, actual_store, actual_raw, bindings):
            assert actual_store is store and actual_raw is raw and bindings == case[1]
            self.calls += 1
            try:
                yield None  # Explicit fallback keeps the reference consumer.
            finally:
                self.stats = {"closed": True, "effective_backend": "python"}

    backend = Backend()
    options = dict(source="test", ha_url="", token="", actual_mappings=case[2], quality_bindings=case[1],
                   now=case[-1], lookback_hours=2)
    with freeze_time(case[-1] + timedelta(hours=2), real_asyncio=True):
        reference_report = await subject.archive_observations(store, **options)
        reference = list(subject.captures_from_archive(store, source="test:actuals", kind="actuals"))[-1]
        native_report = await subject.archive_observations(store, **options, quality_backend=backend)
        saved = list(subject.captures_from_archive(store, source="test:actuals", kind="actuals"))[-1]
    assert reference_report["complete"] and native_report["complete"]
    assert backend.calls == 1 and native_report["quality_backend"] == backend.stats
    assert "quality_backend" not in reference_report and "quality_backend" not in saved
    assert canonical_bytes(saved) == canonical_bytes(reference)
    assert raw == before and saved["raw"] == raw["raw"]
