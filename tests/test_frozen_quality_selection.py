"""Pinned frozen selection preserves native decisions and excluded evidence."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import importlib.util
from pathlib import Path
import shutil
import sqlite3
import sys
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

from freezegun import freeze_time
import pytest

from custom_components.adaptive_solar.core.archive import ArchiveStore
from scripts import continuous_quality, profile_quality
from tests.test_actual_quality import envelope, quality_case, rehash

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "test-source"


def append(store, source, events):
    cursor = store.checkpoint(source)
    generation = events[0]["generation"]
    page = dict(schema=1, generation=generation, oldest_sequence=1, requested_cursor=cursor,
                next_cursor=f"{generation}:{events[-1]['sequence']}",
                events=[{k: v for k, v in event.items() if k != "source"} for event in events], gap=None)
    if cursor and cursor.split(":")[0] != generation:
        page["gap"] = dict(reason="generation_changed", **{"from": 1, "to": 0})
    store.ingest_page(source, page)


def load(path, prefix):
    name = prefix + uuid4().hex
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def case_factory(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    modules = []

    def make(start=None, hours=2, ignored_payload=None):
        folder = tmp_path / uuid4().hex
        events, bindings, mappings, start, end, receipt = quality_case(start, hours=hours)
        bindings["schema"] = "adaptive-solar-actual-quality-bindings-v2"
        binding = bindings["bindings"][0]
        binding["valid_to"] = (end + timedelta(days=7)).isoformat()
        for facet in binding["qualification"].values():
            facet["validated_at"] = (start - timedelta(hours=2)).isoformat()
        for event in events[1:]:
            event["payload"]["source_binding"] = dict(schema=1, energy_entity_id=binding["statistic_id"],
                config_sha256=binding["config_sha256"], producer_sha256=binding["producer_sha256"])
            rehash(event)
        store = ArchiveStore(folder / "archive")
        append(store, SOURCE, events[:1])
        append(store, SOURCE, events[1:])
        old = deepcopy(events[1]["payload"])
        old.update(start=(start - timedelta(days=10)).isoformat(), end=(start - timedelta(days=10, minutes=-15)).isoformat())
        append(store, SOURCE, [envelope("qualified_interval", old, len(events) + 1, start - timedelta(days=9))])
        append(store, SOURCE, [envelope("diagnostic", ignored_payload or {"ignored": True}, len(events) + 2, receipt)])
        append(store, "other-source", [envelope("diagnostic", {}, 1, receipt, source="other-source")])
        rows, cursor = [], start - timedelta(hours=1)
        while cursor < end:
            rows.append(dict(start=cursor.timestamp() * 1000, end=(cursor + timedelta(hours=1)).timestamp() * 1000, change=1))
            cursor += timedelta(hours=1)
        from scripts.capture_actuals import build_raw_capture
        raw = build_raw_capture([dict(statistic_id="sensor.energy", has_sum=True, unit_class="energy",
            statistics_unit_of_measurement="kWh", display_unit_of_measurement="kWh")],
            {"sensor.energy": rows}, mappings, start, end, receipt)
        source = folder / "source"
        for directory in ("custom_components", "scripts"):
            for path in (ROOT / directory).rglob("*"):
                if path.is_file() and path.suffix in {".py", ".json"}:
                    target = source / path.relative_to(ROOT)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, target)
        native = load(source / "custom_components/adaptive_solar/core/archive.py", "selection_archive_")
        helper = load(source / "scripts/frozen_quality_selection.py", "selection_helper_")
        modules.extend([native.__name__, helper.__name__])
        reader = object.__new__(native.ArchiveStore)
        reader.root, reader.originals = store.root, store.originals
        query = helper.query_from_capture(raw, bindings)
        return SimpleNamespace(helper=helper, native=native, reader=reader, store=store, raw=raw,
                               bindings=bindings, query=query, events=events, source=source, folder=folder)

    yield make
    for name in modules:
        sys.modules.pop(name, None)


def scope(case, plan, **kwargs):
    return case.helper.selection_scope(case.reader, plan, expected_plan_sha256=case.helper.plan_sha256(plan),
                                       query=kwargs.pop("query", case.query), **kwargs)


def test_decisions_equal_with_fewer_native_original_reads_and_no_lock_file(case_factory, monkeypatch):
    case = case_factory()
    plan = case.helper.build_plan(case.reader, case.query)
    reads, original = [], case.native.ArchiveStore._read_original

    def counted(self, path):
        reads.append(path)
        return original(self, path)
    monkeypatch.setattr(case.native.ArchiveStore, "_read_original", counted)
    with freeze_time("2026-11-03T10:00:00Z"):
        full = continuous_quality.derive(case.reader, case.raw, case.bindings)
        full_count = len(reads)
        reads.clear()
        (case.reader.root / ".archive.lock").unlink()
        with scope(case, plan) as selected:
            result = continuous_quality.derive(selected, case.raw, case.bindings)
        assert result == full
    assert len(reads) < full_count
    assert selected.selection_status["scheduled_batches"] < selected.selection_status["candidate_batches"]
    assert not (case.reader.root / ".archive.lock").exists()
    with pytest.raises(ValueError, match="closed"):
        selected.iter_events(source=SOURCE)


@pytest.mark.parametrize("mutation", ["plan", "query", "index", "original", "source", "cache", "runtime"])
def test_changed_plan_query_corpus_or_execution_pins_fail_before_selection(case_factory, mutation, monkeypatch):
    case = case_factory()
    plan = case.helper.build_plan(case.reader, case.query)
    expected, query = case.helper.plan_sha256(plan), deepcopy(case.query)
    if mutation == "plan":
        plan["selected"].clear()
    elif mutation == "query":
        query["bindings_sha256"] = "b" * 64
    elif mutation == "index":
        with sqlite3.connect(case.reader.root / "index.sqlite3") as conn:
            conn.execute("DELETE FROM events WHERE sequence=1")
    elif mutation == "original":
        path = next(case.reader.originals.rglob("*.json.gz"))
        path.write_bytes(path.read_bytes() + b"changed")
    elif mutation == "source":
        with (case.source / "custom_components/adaptive_solar/core/replay.py").open("a") as stream:
            stream.write("\n# changed timestamp implementation pin\n")
    elif mutation == "cache":
        cache = case.source / "scripts/__pycache__"
        cache.mkdir()
        (cache / "old.pyc").write_bytes(b"old bytecode")
    else:
        monkeypatch.setattr(case.native, "MAX_EVENT_BYTES", case.native.MAX_EVENT_BYTES - 1)
    with pytest.raises(ValueError):
        with case.helper.selection_scope(case.reader, plan, expected_plan_sha256=expected, query=query):
            pytest.fail("changed evidence must fail before yielding a selected view")


@pytest.mark.parametrize("table,column", [("events", None), ("batches", None), ("batches", "source"),
                                          ("events", "event_id"), ("events", "batch"), ("metadata", "value")])
def test_plan_build_rejects_missing_or_corrupt_authoritative_index(case_factory, table, column):
    case = case_factory()
    with sqlite3.connect(case.reader.root / "index.sqlite3") as conn:
        if column is None:
            conn.execute(f"DELETE FROM {table} WHERE rowid=(SELECT min(rowid) FROM {table})")
        else:
            conn.execute(f"UPDATE {table} SET {column}='wrong' WHERE rowid=(SELECT min(rowid) FROM {table})")
    with pytest.raises(ValueError):
        case.helper.build_plan(case.reader, case.query)


def test_scope_rechecks_after_success_and_rejects_writes_and_unsupported_queries(case_factory):
    case = case_factory()
    plan = case.helper.build_plan(case.reader, case.query)
    with pytest.raises(ValueError, match="changed"):
        with scope(case, plan) as selected:
            for operation in (lambda: selected.pin("bad"), lambda: selected.rebuild_index(),
                              lambda: selected.iter_events(source="foreign"),
                              lambda: selected.iter_events(source=SOURCE, dataset="dataset")):
                with pytest.raises(ValueError):
                    operation()
            case.raw["raw"]["statistics"]["sensor.energy"][0]["change"] = 2
            case.query["raw_sha256"] = case.helper.plan_sha256(case.raw)


def test_native_dependency_outside_selection_is_verified_and_ambiguity_preserved(case_factory):
    case = case_factory()
    dependency = list(case.reader.iter_events(source=SOURCE))[-1]
    plan = case.helper.build_plan(case.reader, case.query)
    with scope(case, plan) as selected:
        assert selected.resolve_events([dependency["event_id"]], source=SOURCE,
            generation=dependency["generation"]) == [dependency]
        assert all(row["event_id"] != dependency["event_id"] for row in selected.iter_events(source=SOURCE))
    duplicate = envelope("diagnostic", {}, len(case.events) + 3, datetime(2026, 6, 1, 15, tzinfo=UTC))
    duplicate["event_id"] = dependency["event_id"]
    rehash(duplicate)
    append(case.store, SOURCE, [duplicate])
    plan = case.helper.build_plan(case.reader, case.query)
    with scope(case, plan) as selected:
        with pytest.raises(ValueError, match="Ambiguous"):
            selected.resolve_events([dependency["event_id"]], source=SOURCE, generation=dependency["generation"])


def test_future_received_malformed_time_is_conservative_and_query_never_filters_receipts(case_factory):
    case = case_factory()
    future = envelope("qualified_interval", {"start": "not-a-time"}, len(case.events) + 3,
                      datetime(2099, 1, 1, tzinfo=UTC))
    append(case.store, SOURCE, [future])
    plan = case.helper.build_plan(case.reader, case.query)
    with scope(case, plan) as selected:
        assert any(event["event_id"] == future["event_id"] for event in selected.iter_events(source=SOURCE))
        result = continuous_quality.derive(selected, case.raw, case.bindings)
    assert len(result["normalization"]["records"]) == 2


@pytest.mark.parametrize("date,hours", [("2026-03-29", 23), ("2026-10-25", 25)])
def test_both_dst_days_preserve_all_hour_decisions(case_factory, date, hours):
    start = datetime.fromisoformat(date).replace(tzinfo=ZoneInfo("Europe/Berlin")).astimezone(UTC)
    case = case_factory(start, hours)
    plan = case.helper.build_plan(case.reader, case.query)
    full = continuous_quality.derive(case.reader, case.raw, case.bindings)
    with scope(case, plan) as selected:
        result = continuous_quality.derive(selected, case.raw, case.bindings)
    assert profile_quality.decisions(result) == profile_quality.decisions(full)
    assert len(result["normalization"]["records"]) == hours


def test_deeper_reuse_falls_back_and_does_not_hide_native_recursion_rejection(case_factory):
    payload = 0
    for _ in range(800):
        payload = [payload]
    case = case_factory(ignored_payload={"deep": payload})
    plan = case.helper.build_plan(case.reader, case.query)

    def deeply(count, reader):
        if count:
            return deeply(count - 1, reader)
        return list(reader.iter_events(source=SOURCE))

    with pytest.raises(ValueError):
        deeply(220, case.reader)
    with scope(case, plan) as selected:
        with pytest.raises(ValueError):
            deeply(220, selected)
        assert selected.selection_status["headroom_fallbacks"] > 0


def test_custom_read_override_and_budget_limits_cannot_attest_omitted_evidence(case_factory):
    case = case_factory()
    case.reader._read_original = lambda path: {}
    with pytest.raises(ValueError, match="overrides"):
        case.helper.build_plan(case.reader, case.query)
    del case.reader._read_original
    with pytest.raises(ValueError, match="budget"):
        case.helper.build_plan(case.reader, case.query, max_events=1)


def test_reserved_stack_failure_retries_flat_and_keeps_otherwise_irrelevant_batch(case_factory, monkeypatch):
    payload = 0
    for _ in range(900):
        payload = [payload]
    case = case_factory(ignored_payload={"deep": payload})
    diagnostic = list(case.reader.iter_events(source=SOURCE))[-1]
    with sqlite3.connect(case.reader.root / "index.sqlite3") as conn:
        batch = conn.execute("SELECT batch FROM events WHERE event_id=?", (diagnostic["event_id"],)).fetchone()[0]
    path = case.reader._original_path(batch)
    original = case.native.ArchiveStore._read_original
    assert original(case.reader, path)["page"]["events"][0]["kind"] == "diagnostic"
    attempts = []

    def watched(self, candidate):
        try:
            result = original(self, candidate)
        except ValueError:
            if candidate == path:
                attempts.append("failed")
            raise
        if candidate == path:
            attempts.append("passed")
        return result

    monkeypatch.setattr(case.native.ArchiveStore, "_read_original", watched)
    plan = case.helper.build_plan(case.reader, case.query)
    assert attempts == ["failed", "passed"]
    assert batch in plan["selected"]
    with scope(case, plan) as selected:
        assert any(event["event_id"] == diagnostic["event_id"] for event in selected.iter_events(source=SOURCE))
