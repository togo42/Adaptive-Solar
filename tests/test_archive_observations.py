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
