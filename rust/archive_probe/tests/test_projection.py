"""Explicit projection gate against an exported public compact-consumer source.

ADAPTIVE_SOLAR_QUALITY_SOURCE_ROOT needs public source files only, never private
installation mappings or archives. The four contract files are pinned below.
"""
from copy import deepcopy
import gc
from datetime import UTC, datetime, timedelta
import gzip
import hashlib
import importlib
import json
import os
from pathlib import Path
import signal
import sys
import weakref
from types import ModuleType
from uuid import uuid4

import pytest

from custom_components.adaptive_solar.core import archive
from scripts import rust_archive_probe
from tests.test_actual_quality import envelope, quality_case, rehash

COMPACT_CONTRACT = {
    "scripts/continuous_quality.py": "f98779199a443d4d97466ee6d9d4ca3922fed977ba745be77d11703036a9c543",
    "custom_components/adaptive_solar/core/actual_quality.py": "27d5929efca61383470054a232fb1de7c65460c3e154275b4936563ea2570ef6",
    "scripts/capture_actuals.py": "50058b837b1d30eb09c4fea33b2ff407c6db1610a3eab3dec7c73f373a214c7e",
    "scripts/actual_quality_io.py": "17e7583b90edf95f49bda1754e4429822b7ad81afc52308f46020e6144f0309c",
}


@pytest.fixture(scope="module")
def kernel():
    path, sha = os.environ.get("ADAPTIVE_SOLAR_RUST_MODULE"), os.environ.get("ADAPTIVE_SOLAR_RUST_MODULE_SHA256")
    if not path or not sha:
        pytest.fail("The explicit projection gate requires a Rust module and SHA256")
    path = Path(path).resolve()
    assert rust_archive_probe._file_sha(path) == sha
    module = rust_archive_probe._load_extension(path, sha)
    assert module.PROTOCOL_VERSION == 1 and module.QUALITY_PROJECTION_VERSION == 2
    return module


@pytest.fixture(scope="module")
def contract():
    raw = os.environ.get("ADAPTIVE_SOLAR_QUALITY_SOURCE_ROOT")
    if not raw:
        pytest.fail("Projection tests require the frozen compact-consumer source root")
    root = Path(raw).resolve()
    for name, expected in COMPACT_CONTRACT.items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected, name
    alias = "projection_contract_" + uuid4().hex
    for name, path in ((alias, root / "custom_components"),
                       (alias + ".adaptive_solar", root / "custom_components/adaptive_solar"),
                       (alias + ".adaptive_solar.core", root / "custom_components/adaptive_solar/core")):
        package = ModuleType(name)
        package.__path__ = [str(path)]
        package.__package__ = name
        sys.modules[name] = package
    value = importlib.import_module(alias + ".adaptive_solar.core.actual_quality")
    assert callable(value.configuration_from_forecast)
    yield value
    for name in list(sys.modules):
        if name == alias or name.startswith(alias + "."):
            sys.modules.pop(name, None)


def write_page(folder, events, *, source="test-source", order=1, request=None):
    clean = [{key: value for key, value in event.items() if key != "source"} for event in events]
    generation = clean[0]["generation"]
    page = dict(schema=1, generation=generation, oldest_sequence=clean[0]["sequence"],
                requested_cursor=request, next_cursor=f"{generation}:{clean[-1]['sequence']}", events=clean, gap=None)
    start = int(request.split(":")[1]) if request and request.split(":")[0] == generation else 0
    if request and request.split(":")[0] != generation:
        page["gap"] = {"reason": "generation_changed", "from": 1, "to": page["oldest_sequence"] - 1}
    elif start < page["oldest_sequence"] - 1:
        page["gap"] = {"reason": "retention_or_overflow", "from": start + 1, "to": page["oldest_sequence"] - 1}
    stamp = datetime(2026, 6, 2, tzinfo=UTC).isoformat()
    wrapper = dict(schema=1, source=source, ingest_order=order, stored_at=stamp, archive_started_at=stamp, page=page)
    raw = json.dumps(wrapper, ensure_ascii=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(raw).hexdigest()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (digest + ".json.gz")
    path.write_bytes(gzip.compress(raw, mtime=0))
    return str(path)


def query_for(case):
    _, bindings, _, start, end, _ = case
    row = bindings["bindings"][0]
    return dict(schema=1, source="test-source", target_start=start.isoformat(), target_end=end.isoformat(),
                periods=[dict(valid_from=row["valid_from"], valid_to=row["valid_to"], config_event_id=row["config_event_id"])],
                bindings_sha256=hashlib.sha256(archive.canonical_bytes(bindings)).hexdigest())


def project(kernel, paths, query, **kwargs):
    return kernel.project_quality_source(paths, json.dumps(query, ensure_ascii=True).encode(),
        max_page_bytes=archive.MAX_PAGE_BYTES, max_event_bytes=archive.MAX_EVENT_BYTES,
        max_page_events=archive.MAX_PAGE_EVENTS, **kwargs)


def test_opaque_proofs_match_compact_factory_and_exact_original_working_budget(kernel, contract, tmp_path):
    case = quality_case()
    events, _, _, _, _, _ = case
    path = write_page(tmp_path, events)
    result = project(kernel, [path], query_for(case))
    assert type(result) is kernel.VerifiedQualitySource
    items = result.items()
    assert len(items) == len(events)
    proof = items[0]
    expected = contract.configuration_from_forecast(events[0], retain_site=True)
    assert type(proof) is kernel.VerifiedConfiguration and proof["payload"] is proof
    assert proof.configuration_bytes == expected._canonical
    assert proof.reference_bytes == archive.canonical_bytes(contract._reference(events[0]))
    assert proof.original_full_working_size == len(archive.canonical_bytes(events[0]))
    assert proof.original_batch_sha256 == Path(path).name.removesuffix(".json.gz")
    assert proof.anchor and proof.get("payload_ref") is None and "payload_ref" not in proof
    assert proof["kind"] == "forecast_issued"
    assert [json.loads(item) for item in items[1:]] == events[1:]
    assert result.original_files == 1 and result.original_events == result.selected_events == len(events)
    assert result.query_sha256 == hashlib.sha256(archive.canonical_bytes(query_for(case))).hexdigest()
    assert result.bindings_sha256 == query_for(case)["bindings_sha256"]
    for cls in (kernel.VerifiedConfiguration, kernel.VerifiedQualitySource, kernel.VerifiedQualityItems):
        with pytest.raises(TypeError):
            cls()
        with pytest.raises(TypeError):
            object.__new__(cls)
    with pytest.raises(AttributeError):
        proof.anchor = False
    with pytest.raises(AttributeError):
        _ = proof.__dict__
    with pytest.raises(TypeError):
        json.dumps(proof)


def test_anchor_outside_period_other_generations_and_future_receipts_are_retained(kernel, contract, tmp_path):
    case = quality_case()
    anchor = deepcopy(case[0][0])
    anchor["payload"]["issued_at"] = (case[3] - timedelta(days=30)).isoformat()
    anchor["received_at"] = (case[3] - timedelta(days=30, minutes=-1)).isoformat()
    rehash(anchor)
    first = write_page(tmp_path / "one", [anchor])
    changed = deepcopy(anchor)
    changed.update(generation=str(uuid4()), sequence=1, event_id="other-generation",
                   received_at=datetime(2099, 1, 1, tzinfo=UTC).isoformat())
    changed["payload"]["issued_at"] = case[3].isoformat()
    changed["payload"]["software"]["source_sha256"] = "b" * 64
    rehash(changed)
    second = write_page(tmp_path / "two", [changed], order=2)
    result = project(kernel, [first, second], query_for(case))
    proofs = result.items()
    assert [item["event_id"] for item in proofs] == [anchor["event_id"], changed["event_id"]]
    assert proofs[0].anchor and not proofs[1].anchor
    assert proofs[1]["received_at"].startswith("2099")
    assert proofs[1].configuration_bytes == contract.configuration_from_forecast(changed, retain_site=False)._canonical


def test_dedup_precedes_kind_time_selection_and_preserves_path_order(kernel, tmp_path):
    case = quality_case()
    forecast = case[0][0]
    diagnostic = envelope("diagnostic", {}, 1, case[3])
    diagnostic["event_id"] = forecast["event_id"]
    rehash(diagnostic)
    ignored = write_page(tmp_path / "first", [diagnostic])
    later = write_page(tmp_path / "second", [forecast], order=2)
    result = project(kernel, [ignored, later], query_for(case))
    assert result.items() == () and result.original_events == 2
    reverse = project(kernel, [later, ignored], query_for(case))
    assert len(reverse.items()) == 1 and reverse.items()[0]["kind"] == "forecast_issued"


@pytest.mark.parametrize("bad", ["chunk", "chronology", "time", "source", "checksum", "extra_query"])
def test_any_unsupported_source_is_atomic_none_not_partial_projection(kernel, tmp_path, bad):
    case = quality_case()
    first = write_page(tmp_path / "good", case[0])
    event = deepcopy(case[0][0])
    event.update(sequence=1, generation=str(uuid4()), event_id="bad-later")
    if bad == "chunk":
        event["payload"]["payload_ref"] = {}
    elif bad == "chronology":
        event["payload"]["computed_at"] = datetime(2099, 1, 1, tzinfo=UTC).isoformat()
    elif bad == "time":
        event["payload"]["issued_at"] = "not-a-time"
        event["received_at"] = datetime(2099, 1, 1, tzinfo=UTC).isoformat()
    rehash(event)
    second = write_page(tmp_path / "bad", [event], order=2, source="foreign" if bad == "source" else "test-source")
    if bad == "checksum":
        Path(second).write_bytes(Path(second).read_bytes() + b"bad trailing bytes")
    query = query_for(case)
    if bad == "extra_query":
        query["as_of"] = case[-1].isoformat()
    assert project(kernel, [first, second], query) is None


@pytest.mark.parametrize("limits", [{"max_selected_events": 1}, {"max_retained_bytes": 1}, {"max_depth": 1}])
def test_resource_bounds_return_none(kernel, tmp_path, limits):
    case = quality_case()
    path = write_page(tmp_path, case[0])
    assert project(kernel, [path], query_for(case), **limits) is None


def test_interval_selection_keeps_complete_cross_hour_originals_and_mixed_item_order(kernel, contract, tmp_path):
    case = quality_case()
    original = case[0][0]
    later = deepcopy(original)
    later.update(sequence=3, event_id="later-configuration", received_at=case[0][1]["received_at"])
    later["payload"]["issued_at"] = case[3].isoformat()
    rehash(later)
    events = [original, case[0][1], later]
    result = project(kernel, [write_page(tmp_path, events)], query_for(case))
    items = result.items()
    assert type(items[0]) is kernel.VerifiedConfiguration and type(items[1]) is bytes
    assert type(items[2]) is kernel.VerifiedConfiguration
    assert json.loads(items[1]) == case[0][1]
    assert json.loads(items[1])["payload"]["start"] < case[3].isoformat()
    assert items[2].configuration_bytes == contract.configuration_from_forecast(later, retain_site=False)._canonical


@pytest.mark.parametrize("exception_type", [RuntimeError, ValueError, KeyboardInterrupt, SystemExit])
def test_pending_python_signals_propagate_out_of_projection(kernel, tmp_path, exception_type):
    class ProjectionSignal(exception_type):
        pass

    def interrupt(signum, frame):
        raise ProjectionSignal("functional signal gate")

    path = write_page(tmp_path, [envelope("diagnostic", {"floats": [n / 7 for n in range(512)]}, 1, datetime(2026, 6, 1, tzinfo=UTC))])
    old_handler = signal.signal(signal.SIGALRM, interrupt)
    try:
        with pytest.raises(ProjectionSignal):
            signal.setitimer(signal.ITIMER_REAL, 0.01)
            project(kernel, [path] * 2000, query_for(quality_case()))
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)


def test_numeric_capi_errors_match_native_and_do_not_leak_into_raw_protocol(kernel, tmp_path):
    old_limit = sys.get_int_max_str_digits()
    try:
        sys.set_int_max_str_digits(0)
        event = envelope("diagnostic", {"huge": 10**4500}, 1, datetime(2026, 6, 1, tzinfo=UTC))
        path = write_page(tmp_path / "huge", [event])
        sys.set_int_max_str_digits(4300)
        reader = object.__new__(archive.ArchiveStore)
        with pytest.raises(ValueError) as native_error:
            reader._read_original(Path(path))
        with pytest.raises(ValueError) as projected_error:
            project(kernel, [path], query_for(quality_case()))
        assert type(projected_error.value) is type(native_error.value)
        assert str(projected_error.value) == str(native_error.value)
        assert kernel.read_original(path, archive.MAX_PAGE_BYTES, archive.MAX_EVENT_BYTES,
                                    archive.MAX_PAGE_EVENTS) is None
        clean = write_page(tmp_path / "clean", quality_case()[0])
        assert project(kernel, [clean], query_for(quality_case())) is not None
    finally:
        sys.set_int_max_str_digits(old_limit)


def test_single_consumption_preserves_counts_and_frees_proof_capabilities(kernel, tmp_path):
    case = quality_case()
    result = project(kernel, [write_page(tmp_path, case[0])], query_for(case))
    count = result.selected_events
    items = result.take_items()
    assert type(items) is kernel.VerifiedQualityItems and iter(items) is items
    assert len(items) == count
    with pytest.raises(RuntimeError, match="consumed"):
        result.take_items()
    with pytest.raises(RuntimeError, match="consumed"):
        result.items()
    proof = next(items)
    assert type(proof) is kernel.VerifiedConfiguration and len(items) == count - 1
    weak = weakref.ref(proof)
    assert weak() is proof
    del proof
    gc.collect()
    assert weak() is None
    remaining = [json.loads(item) for item in items]
    assert remaining == case[0][1:]
    assert len(items) == 0 and result.selected_events == count
    items.close()


def test_stream_close_releases_remaining_items_without_reopening_consumption(kernel, tmp_path):
    case = quality_case()
    result = project(kernel, [write_page(tmp_path, case[0])], query_for(case))
    items = result.take_items()
    items.close()
    assert len(items) == 0 and list(items) == []
    assert result.selected_events == len(case[0])
    with pytest.raises(RuntimeError, match="consumed"):
        result.take_items()
