"""Production native-quality guards and complete ArchiveStore equivalence.

The default tests use an explicit protocol double, never an optional binary.
Set ADAPTIVE_SOLAR_TEST_NATIVE_QUALITY_BINARY to run the separate real-kernel
positive control against a live ArchiveStore and its normal read lock.
"""
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import gc
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import threading
from types import SimpleNamespace
import weakref

from freezegun import freeze_time
import pytest

from custom_components.adaptive_solar.core import actual_quality, archive
from scripts import continuous_quality, native_quality_backend as subject
from tests.test_actual_quality import rehash
from tests.test_capture_actuals import capture
from tests.test_continuous_quality import continuous_case, store_case


def canonical(value):
    return archive.canonical_bytes(value)


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


class FakeConfiguration:
    """Opaque protocol double with the same weak-reference lifetime contract."""

    def __init__(self, event, anchor):
        self.event = event
        self.anchor = anchor
        self.configuration_bytes = actual_quality.configuration_from_forecast(event, retain_site=anchor)._canonical
        self.original_full_working_size = len(canonical(event))

    def __getitem__(self, key):
        return self.event[key]


class FakeItems:
    def __init__(self, items):
        self.pending = list(items)
        self.closed = False

    def __len__(self):
        return len(self.pending)

    def __iter__(self):
        return self

    def __next__(self):
        if not self.pending:
            raise StopIteration
        return self.pending.pop(0)

    def close(self):
        self.closed = True
        self.pending.clear()


class FakeSource:
    def __init__(self, paths, query, extension):
        self.source = query["source"]
        self.query_sha256 = digest(query)
        self.bindings_sha256 = query["bindings_sha256"]
        self.original_files = len(paths)
        events = []
        for path in paths:
            value = json.loads(gzip.decompress(Path(path).read_bytes()))
            events.extend({"source": value["source"], **event} for event in value["page"]["events"])
        self.original_events = len(events)
        anchors = {row["config_event_id"] for row in query["periods"]}
        self.pending = [FakeConfiguration(event, event["event_id"] in anchors)
                        if event["kind"] == "forecast_issued" else canonical(event)
                        for event in events if event["kind"] in {"forecast_issued", "qualified_interval"}]
        self.selected_events = len(self.pending)
        self.extension = extension

    def take_items(self):
        if self.pending is None:
            raise ValueError("native items can only be taken once")
        result = FakeItems(self.pending)
        self.pending = None
        self.extension.items.append(weakref.ref(result))
        return result


class FakeExtension:
    PROTOCOL_VERSION = 1
    QUALITY_PROJECTION_VERSION = 2
    VerifiedConfiguration = FakeConfiguration
    VerifiedQualitySource = FakeSource
    VerifiedQualityItems = FakeItems

    def __init__(self):
        self.calls = []
        self.items = []
        self.result_hook = lambda result: result

    def project_quality_source(self, paths, query, **limits):
        query = json.loads(query)
        self.calls.append((paths, query, limits))
        return self.result_hook(FakeSource(paths, query, self))


@pytest.fixture
def policy_store(tmp_path):
    case = continuous_case()
    store = store_case(tmp_path, case)
    raw = capture(start=case[3], end=case[4], received=case[-1])
    return SimpleNamespace(case=case, store=store, raw=raw, bindings=case[1])


def write_manifest(tmp_path, monkeypatch, binary=None):
    """Use a disposable release root, leaving repository/runtime files alone."""
    original_root = Path(subject.__file__).resolve().parents[1]
    root = tmp_path / "release"
    for name in subject.SOURCE_FILES:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original_root / name, target)
    library = root / "native/lib_archive_probe.so"
    library.parent.mkdir(parents=True)
    if binary is None:
        library.write_bytes(b"explicit test double; never dynamically loaded")
    else:
        shutil.copyfile(binary, library)
    monkeypatch.setattr(subject, "ROOT", root)
    monkeypatch.setattr(subject, "_validate_module_origins", lambda _: None)
    manifest = {"schema": "adaptive-solar-native-quality-runtime-v1", "protocol_version": 2,
                "source_root": str(root),
                "sources": {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                            for name in subject.SOURCE_FILES},
                "binary": {"path": "native/lib_archive_probe.so",
                           "sha256": hashlib.sha256(library.read_bytes()).hexdigest()},
                "runtime": subject._runtime_snapshot()}
    path = tmp_path / "native-runtime.json"
    path.write_bytes(canonical(manifest))
    return SimpleNamespace(root=root, library=library, path=path, manifest=manifest)


def load(case):
    return subject.load_backend(case.path, hashlib.sha256(case.path.read_bytes()).hexdigest())


@pytest.fixture
def native(tmp_path, monkeypatch):
    release = write_manifest(tmp_path, monkeypatch)
    extension = FakeExtension()
    monkeypatch.setattr(subject._native_probe, "_load_extension", lambda *args: extension)
    return SimpleNamespace(**vars(release), extension=extension, backend=load(release))


def derive(case, backend=None):
    with freeze_time(case.case[-1] + timedelta(hours=2)):
        return continuous_quality.derive(case.store, case.raw, case.bindings, backend=backend)


def test_default_path_keeps_reference_output_and_never_loads_extension(policy_store, monkeypatch):
    monkeypatch.setattr(subject._native_probe, "_load_extension",
                        lambda *args: pytest.fail("Python default must not load a native extension"))
    raw = deepcopy(policy_store.raw)
    result = derive(policy_store)
    with freeze_time(policy_store.case[-1] + timedelta(hours=2)):
        default = continuous_quality.derive(policy_store.store, policy_store.raw, policy_store.bindings)
    assert canonical(result) == canonical(default)
    assert result["quality_derivation"]["summary"]["roof"]["qualified_hours"] == 2
    assert result["raw"] == raw["raw"] and policy_store.raw == raw


def test_default_error_closes_archive_reader_in_its_worker_before_returning_traceback(policy_store, monkeypatch):
    closed_on, readers = [], []
    real_db, real_iter = policy_store.store._db, policy_store.store.iter_events

    @contextmanager
    def tracked_db(*args, **kwargs):
        try:
            with real_db(*args, **kwargs) as connection:
                yield connection
        finally:
            closed_on.append(threading.get_ident())

    def tracked_iterator(**kwargs):
        reader = real_iter(**kwargs)
        readers.append(weakref.ref(reader))
        return reader

    monkeypatch.setattr(policy_store.store, "_db", tracked_db)
    monkeypatch.setattr(policy_store.store, "iter_events", tracked_iterator)
    monkeypatch.setattr(continuous_quality, "MAX_BYTES", 1)

    def failed_worker():
        try:
            continuous_quality.derive(policy_store.store, policy_store.raw, policy_store.bindings)
        except ValueError as exc:
            # Preserve the real traceback crossing the executor boundary. It
            # must not own an open SQLite generator from the worker thread.
            natural_close = list(closed_on)
            for reference in readers:
                reader = reference()
                if reader is not None:
                    reader.close()  # Clean a regression up on its own thread.
            return natural_close, threading.get_ident(), exc
        raise AssertionError("The bounded selection must fail")

    with ThreadPoolExecutor(max_workers=1) as executor:
        natural_close, worker, failure = executor.submit(failed_worker).result(timeout=10)
    assert "bounded budget" in str(failure)
    assert natural_close == [worker]
    assert all(reference() is None or reference().gi_frame is None for reference in readers)


def test_live_archive_native_result_matches_complete_reference_and_preserves_methods(native, policy_store):
    originals = {name: getattr(archive.ArchiveStore, name)
                 for name in ("iter_events", "_read_original", "_read_lock", "_event_batches")}
    original_derive = continuous_quality.derive
    raw, bindings = deepcopy(policy_store.raw), deepcopy(policy_store.bindings)
    expected = derive(policy_store)
    result = derive(policy_store, native.backend)
    assert canonical(result) == canonical(expected)
    assert policy_store.raw == raw and policy_store.bindings == bindings
    assert native.backend.stats["sources_projected"] == 1
    assert native.backend.stats["configuration_proofs"] == 1
    assert native.backend.stats["source_fallbacks"] == 0
    assert native.backend.stats["closed"]
    assert continuous_quality.derive is original_derive
    assert all(getattr(archive.ArchiveStore, name) is value for name, value in originals.items())


def test_native_projects_under_the_real_read_lock(native, policy_store, monkeypatch):
    held = []
    real_lock = archive._lock

    @contextmanager
    def recording_lock(root):
        with real_lock(root):
            held.append(root)
            try:
                yield
            finally:
                held.pop()

    original = native.extension.project_quality_source

    def checked_project(*args, **kwargs):
        assert policy_store.store.root in held
        return original(*args, **kwargs)

    monkeypatch.setattr(archive, "_lock", recording_lock)
    monkeypatch.setattr(native.extension, "project_quality_source", checked_project)
    derive(policy_store, native.backend)
    assert native.backend.stats["sources_projected"] == 1
    assert not held


@pytest.mark.parametrize("method", ["iter_events", "_read_original", "_original_path", "_read_lock", "_event_batches"])
@pytest.mark.parametrize("placement", ["instance", "subclass"])
def test_reader_overrides_preserve_original_semantics(native, policy_store, method, placement):
    original = getattr(archive.ArchiveStore, method)
    calls = []

    def override(self, *args, **kwargs):
        calls.append(method)
        return original(self, *args, **kwargs)

    if placement == "subclass":
        custom = type("CustomArchive", (archive.ArchiveStore,), {method: override})(policy_store.store.root)
    else:
        custom = policy_store.store
        setattr(custom, method, override.__get__(custom, type(custom)))
    policy_store.store = custom
    expected = derive(policy_store)
    calls.clear()
    assert canonical(derive(policy_store, native.backend)) == canonical(expected)
    assert calls
    assert not native.extension.calls
    assert native.backend.stats["fallback_reasons"] == {"custom_reader": 1}


@pytest.mark.parametrize("representation", ["list", "unhashable_iterator"])
def test_narrow_custom_reader_preserves_all_evidence_and_closes_optional_iterator(native, policy_store, representation):
    events = list(policy_store.store.iter_events(source="test-source"))
    events[2]["payload"]["source_binding"]["producer_sha256"] = "b" * 64
    rehash(events[2])
    calls, iterators = [], []

    class UnhashableIterator:
        __hash__ = None

        def __init__(self, values):
            self.values = iter(values)
            self.closed = False

        def __iter__(self):
            return self

        def __next__(self):
            return next(self.values)

        def close(self):
            self.closed = True

    class NarrowReader(archive.ArchiveStore):
        def iter_events(self, *, source):
            calls.append(source)
            values = deepcopy(events)
            if representation == "list":
                return values
            iterator = UnhashableIterator(values)
            iterators.append(iterator)
            return iterator

    policy_store.store = NarrowReader(policy_store.store.root)
    expected = derive(policy_store)
    assert expected["quality_derivation"]["summary"]["roof"]["qualified_hours"] == 1
    calls.clear()
    assert canonical(derive(policy_store, native.backend)) == canonical(expected)
    assert calls == ["test-source"]
    assert not native.extension.calls
    assert native.backend.stats["fallback_reasons"] == {"custom_reader": 1}
    assert native.backend.stats["effective_backend"] == "python"
    if iterators:
        assert iterators[-1].closed


@pytest.mark.parametrize("source_file,allowed_name", [
    ("custom_components/adaptive_solar/core/archive.py", "SUPPORTED_ARCHIVE_SOURCES"),
    ("custom_components/adaptive_solar/core/actual_quality.py", "SUPPORTED_FACTORY_SOURCES"),
])
def test_correct_source_hash_still_needs_qualified_protocol_semantics(tmp_path, monkeypatch, source_file, allowed_name):
    case = write_manifest(tmp_path, monkeypatch)
    assert case.manifest["sources"][source_file] in getattr(subject, allowed_name)
    monkeypatch.setattr(subject, allowed_name, frozenset())
    monkeypatch.setattr(subject._native_probe, "_load_extension",
                        lambda *args: pytest.fail("Unqualified source semantics must fail before loading native code"))
    with pytest.raises(ValueError, match="Unqualified"):
        load(case)


def test_failed_new_bind_cannot_reuse_previous_success_status(native, policy_store):
    derive(policy_store, native.backend)
    assert native.backend.stats["closed"]
    native.library.write_bytes(b"changed before next bind")
    with pytest.raises(ValueError):
        derive(policy_store, native.backend)
    assert native.backend.stats is None


def test_none_falls_back_for_the_whole_source_without_publishing_partial_items(native, policy_store):
    native.extension.result_hook = lambda result: None
    expected = derive(policy_store)
    assert canonical(derive(policy_store, native.backend)) == canonical(expected)
    assert native.backend.stats["sources_projected"] == 0
    assert native.backend.stats["configuration_proofs"] == 0
    assert native.backend.stats["fallback_reasons"] == {"unsupported_source": 1}


@pytest.mark.parametrize("query", [{}, {"source": "unknown"}, {"source": "test-source", "kind": "qualified_interval"}])
def test_unsupported_queries_keep_the_original_generator_frame(native, policy_store, query):
    expected = list(policy_store.store.iter_events(**query))
    with native.backend.bind(policy_store.store, policy_store.raw, policy_store.bindings) as session:
        iterator = session.iter_events(**query)
        assert iterator.gi_code is archive.ArchiveStore.iter_events.__code__
        assert list(iterator) == expected
    assert not native.extension.calls
    assert native.backend.stats["fallback_reasons"] == {"unsupported_query": 1}


@pytest.mark.parametrize("change", ["source_pin", "gap", "late_receipt", "missing_pin", "meter_unverified"])
def test_native_keeps_negative_source_and_time_evidence(native, tmp_path, change):
    case = continuous_case()
    if change == "source_pin":
        case[0][2]["payload"]["source_binding"]["producer_sha256"] = "b" * 64
        rehash(case[0][2])
    elif change == "gap":
        del case[0][2]
    elif change == "late_receipt":
        case[0][2]["received_at"] = (case[-1] + timedelta(days=1)).isoformat()
        rehash(case[0][2])
    elif change == "missing_pin":
        del case[0][2]["payload"]["source_binding"]
        rehash(case[0][2])
    else:
        case[1]["bindings"][0]["qualification"]["meter"]["verified"] = False
    store = store_case(tmp_path, case)
    data = SimpleNamespace(case=case, store=store, raw=capture(start=case[3], end=case[4], received=case[-1]), bindings=case[1])
    expected = derive(data)
    assert expected["quality_derivation"]["summary"]["roof"]["qualified_hours"] < 2
    assert canonical(derive(data, native.backend)) == canonical(expected)
    assert native.backend.stats["sources_projected"] == 1


def test_full_original_working_size_is_checked_before_compact_proof_accounting(native, policy_store, monkeypatch):
    def oversized(result):
        result.pending[0].original_full_working_size = 100_001
        return result

    native.extension.result_hook = oversized
    monkeypatch.setattr(continuous_quality, "MAX_BYTES", 100_000)
    with pytest.raises(ValueError, match="bounded budget"):
        derive(policy_store, native.backend)
    assert native.backend.stats["configuration_proofs"] == 0
    assert native.backend.stats["closed"]


def test_chunked_anchor_falls_back_atomically_and_keeps_dependency_evidence(native, tmp_path, monkeypatch):
    from custom_components.adaptive_solar import archive_export
    from scripts import capture_actuals
    from tests.test_archive_observations import ingest

    case = continuous_case()
    journal = archive.ArchiveJournal(tmp_path / "chunks")
    anchor = case[0][0]
    monkeypatch.setattr(archive_export, "MAX_INLINE_BYTES", 1)
    for kind, payload, received, identifier in archive_export.payload_events(
            anchor["kind"], anchor["payload"], capture_actuals.utc(anchor["received_at"]), anchor["event_id"]):
        entry = journal.append(kind, payload, received, identifier)
    case[1]["bindings"][0]["generation"] = entry["generation"]
    for event in case[0][1:]:
        journal.append(event["kind"], event["payload"], capture_actuals.utc(event["received_at"]), event["event_id"])
    store = archive.ArchiveStore(tmp_path / "chunk-archive")
    ingest(journal, store, "test-source")
    data = SimpleNamespace(case=case, store=store, raw=capture(start=case[3], end=case[4], received=case[-1]), bindings=case[1])
    native.extension.project_quality_source = lambda *args, **kwargs: None
    expected = derive(data)
    assert expected["quality_derivation"]["summary"]["roof"]["qualified_hours"] == 2
    assert canonical(derive(data, native.backend)) == canonical(expected)
    assert native.backend.stats["sources_projected"] == 0
    assert native.backend.stats["configuration_proofs"] == 0
    assert native.backend.stats["fallback_reasons"] == {"unsupported_source": 1}


def test_original_intervals_and_configurations_still_count_toward_event_budget(native, policy_store, monkeypatch):
    monkeypatch.setattr(actual_quality, "MAX_EVENTS", 1)
    with pytest.raises(ValueError):
        derive(policy_store, native.backend)
    assert native.extension.calls[0][2]["max_selected_events"] == 1
    assert native.backend.stats["closed"]


@pytest.mark.parametrize("failure", [ValueError("native failure"), RuntimeError("native failure"), KeyboardInterrupt(), SystemExit(17)])
def test_extension_errors_and_signals_propagate_and_close_session(native, policy_store, failure):
    def fail(*args, **kwargs):
        raise failure

    native.extension.project_quality_source = fail
    with pytest.raises(type(failure)) as caught:
        derive(policy_store, native.backend)
    assert caught.value is failure
    assert native.backend.stats["closed"]
    assert native.backend.stats["source_fallbacks"] == 0


@pytest.mark.parametrize("failure", [RuntimeError("iterator failure"), KeyboardInterrupt()])
def test_iterator_errors_and_signals_propagate_after_partial_consumption(native, policy_store, monkeypatch, failure):
    original_next = FakeItems.__next__
    reads = 0

    def interrupted_next(iterator):
        nonlocal reads
        reads += 1
        if reads == 2:
            raise failure
        return original_next(iterator)

    monkeypatch.setattr(FakeItems, "__next__", interrupted_next)
    with pytest.raises(type(failure)) as caught:
        derive(policy_store, native.backend)
    assert caught.value is failure
    assert native.backend.stats["closed"]
    assert native.backend.stats["source_fallbacks"] == 0


@pytest.mark.parametrize("field", ["source", "query_sha256", "bindings_sha256", "original_files", "selected_events"])
def test_mismatched_native_query_or_count_never_publishes_partial_results(native, policy_store, field):
    def mismatch(result):
        setattr(result, field, getattr(result, field) + 1 if field.endswith(("files", "events")) else "wrong")
        return result

    native.extension.result_hook = mismatch
    with pytest.raises(ValueError):
        derive(policy_store, native.backend)
    assert native.backend.stats["configuration_proofs"] == 0
    assert native.backend.stats["closed"]


def test_foreign_capability_and_wrong_anchor_are_rejected(native, policy_store):
    with native.backend.bind(policy_store.store, policy_store.raw, policy_store.bindings) as session:
        item = next(session.iter_events(source="test-source"))
        assert session.is_configuration(item)
        foreign = FakeConfiguration(item.event, True)
        with pytest.raises(ValueError, match="scoped|bound|evidence"):
            session.promote_configuration(foreign, anchor=True)
        for anchor in (False, 1, None):
            with pytest.raises(ValueError):
                session.promote_configuration(item, anchor=anchor)
        proof = session.promote_configuration(item, anchor=True)
        assert type(proof) is actual_quality._ForecastConfiguration
        assert proof._canonical == item.configuration_bytes
    with pytest.raises(ValueError):
        session.promote_configuration(item, anchor=True)


def test_configuration_registry_does_not_retain_dropped_capabilities(native, policy_store):
    with native.backend.bind(policy_store.store, policy_store.raw, policy_store.bindings) as session:
        iterator = session.iter_events(source="test-source")
        item = next(iterator)
        reference = weakref.ref(item)
        del item
        next(iterator)
        gc.collect()
        assert reference() is None


def test_native_item_iterator_is_one_shot_and_closed_sessions_cannot_read(native, policy_store):
    with native.backend.bind(policy_store.store, policy_store.raw, policy_store.bindings) as session:
        iterator = session.iter_events(source="test-source")
        assert iter(iterator) is iterator
        values = list(iterator)
        assert values and list(iterator) == []
    with pytest.raises(ValueError):
        session.iter_events(source="test-source")


def test_configuration_from_other_session_is_never_accepted(native, policy_store):
    with native.backend.bind(policy_store.store, policy_store.raw, policy_store.bindings) as first:
        item = next(first.iter_events(source="test-source"))
    with native.backend.bind(policy_store.store, policy_store.raw, policy_store.bindings) as second:
        with pytest.raises(ValueError):
            second.promote_configuration(item, anchor=True)


def test_status_is_a_detached_snapshot(native, policy_store):
    derive(policy_store, native.backend)
    status = native.backend.stats
    status["closed"] = False
    status["fallback_reasons"]["invented"] = 99
    assert native.backend.stats["closed"] is True
    assert "invented" not in native.backend.stats["fallback_reasons"]


def test_abandoned_iterator_and_session_close_release_pending_native_items(native, policy_store):
    with native.backend.bind(policy_store.store, policy_store.raw, policy_store.bindings) as session:
        iterator = session.iter_events(source="test-source")
        item = next(iterator)
        reference = weakref.ref(item)
        del item
        iterator.close()
        del iterator
        gc.collect()
        assert reference() is None
    assert session.stats["closed"]


def test_retained_closed_iterator_does_not_keep_native_source_buffers_alive(native, policy_store):
    with native.backend.bind(policy_store.store, policy_store.raw, policy_store.bindings) as session:
        iterator = session.iter_events(source="test-source")
        next(iterator)
        native_items = native.extension.items[-1]
        iterator.close()
        gc.collect()
        assert native_items() is None
    assert iterator.closed


@pytest.mark.parametrize("failure", [RuntimeError("iterator failure"), KeyboardInterrupt()])
def test_failed_iterator_releases_its_native_buffers_even_if_caller_catches_error(native, policy_store, monkeypatch, failure):
    with native.backend.bind(policy_store.store, policy_store.raw, policy_store.bindings) as session:
        iterator = session.iter_events(source="test-source")
        native_items = native.extension.items[-1]

        def failed_next(_):
            raise failure

        monkeypatch.setattr(FakeItems, "__next__", failed_next)
        with pytest.raises(type(failure)) as caught:
            next(iterator)
        assert caught.value is failure
        # A caller-held Python traceback itself owns failed_next's argument.
        failure.__traceback__ = None
        del caught
        gc.collect()
        assert native_items() is None
        assert iterator.closed


@pytest.mark.parametrize("change", ["raw", "policy"])
def test_input_mutation_prevents_successful_scope_close(native, policy_store, change):
    with pytest.raises(ValueError):
        with native.backend.bind(policy_store.store, policy_store.raw, policy_store.bindings):
            if change == "raw":
                policy_store.raw["capture_id"] = "mutated"
            else:
                policy_store.bindings["bindings"][0]["config_event_id"] = "mutated"
    assert native.backend.stats["closed"]


@pytest.mark.parametrize("member", ["scripts/continuous_quality.py", "native/lib_archive_probe.so"])
def test_release_member_changes_prevent_successful_scope_close(native, policy_store, member):
    with pytest.raises(ValueError):
        with native.backend.bind(policy_store.store, policy_store.raw, policy_store.bindings) as session:
            list(session.iter_events(source="test-source"))
            (native.root / member).write_bytes(b"replaced after native read")
    assert native.backend.stats["closed"]


@pytest.mark.parametrize("change", ["missing", "invalid_json", "manifest_hash", "schema", "protocol", "runtime",
                                    "binary", "binary_hash", "source", "extra_source", "source_symlink"])
def test_requested_invalid_manifest_fails_closed_before_extension_load(tmp_path, monkeypatch, change):
    case = write_manifest(tmp_path, monkeypatch)
    if change == "missing":
        case.path.unlink()
    elif change == "invalid_json":
        case.path.write_bytes(b"{")
    elif change == "manifest_hash":
        pass
    elif change == "schema":
        case.manifest["schema"] = "unknown"
    elif change == "protocol":
        case.manifest["protocol_version"] = True
    elif change == "runtime":
        case.manifest["runtime"]["soabi"] = "wrong"
    elif change == "binary":
        case.library.unlink()
    elif change == "binary_hash":
        case.library.write_bytes(b"replaced binary")
    elif change == "source":
        (case.root / "scripts/continuous_quality.py").write_bytes(b"changed source")
    elif change == "extra_source":
        case.manifest["sources"]["arbitrary.py"] = "a" * 64
    elif change == "source_symlink":
        member = case.root / "scripts/continuous_quality.py"
        target = tmp_path / "aliased-source.py"
        member.rename(target)
        member.symlink_to(target)
    if change not in {"missing", "invalid_json"}:
        case.path.write_bytes(canonical(case.manifest))
    monkeypatch.setattr(subject._native_probe, "_load_extension",
                        lambda *args: pytest.fail("Invalid manifest must fail before loading native code"))
    expected = "f" * 64 if change == "manifest_hash" or not case.path.exists() else hashlib.sha256(case.path.read_bytes()).hexdigest()
    with pytest.raises((ValueError, OSError)):
        subject.load_backend(case.path, expected)


def test_valid_release_ignores_unrelated_data_venv_links_and_python_caches(tmp_path, monkeypatch):
    case = write_manifest(tmp_path, monkeypatch)
    (case.root / "data").symlink_to(tmp_path / "private-data", target_is_directory=True)
    (case.root / ".venv").symlink_to(tmp_path / "shared-runtime", target_is_directory=True)
    cache = case.root / "scripts/__pycache__"
    cache.mkdir()
    (cache / "unused.pyc").write_bytes(b"ordinary interpreter cache")
    monkeypatch.setattr(subject._native_probe, "_load_extension", lambda *args: FakeExtension())
    assert load(case) is not None


def test_source_root_cannot_relabel_already_imported_modules(tmp_path, monkeypatch):
    validate_origins = subject._validate_module_origins
    case = write_manifest(tmp_path, monkeypatch)
    monkeypatch.setattr(subject, "_validate_module_origins", validate_origins)
    monkeypatch.setattr(subject._native_probe, "_load_extension",
                        lambda *args: pytest.fail("Foreign module origins must fail before loading native code"))
    with pytest.raises(ValueError):
        load(case)


@pytest.mark.parametrize("field", ["implementation", "version", "soabi", "gil_disabled", "python_binary_sha256", "dependencies"])
def test_every_runtime_abi_and_dependency_pin_is_enforced(tmp_path, monkeypatch, field):
    case = write_manifest(tmp_path, monkeypatch)
    if field == "dependencies":
        case.manifest["runtime"][field]["numpy"] = "0.0.0"
    else:
        case.manifest["runtime"][field] = 1 if field == "gil_disabled" else "wrong"
    case.path.write_bytes(canonical(case.manifest))
    monkeypatch.setattr(subject._native_probe, "_load_extension",
                        lambda *args: pytest.fail("Runtime mismatch must fail before loading native code"))
    with pytest.raises(ValueError):
        load(case)


@pytest.mark.parametrize("change", ["absolute", "traversal", "symlink", "extra_field", "root"])
def test_manifest_cannot_escape_or_relabel_its_release(tmp_path, monkeypatch, change):
    case = write_manifest(tmp_path, monkeypatch)
    if change == "absolute":
        case.manifest["binary"]["path"] = str(case.library)
    elif change == "traversal":
        case.manifest["binary"]["path"] = "native/../native/lib_archive_probe.so"
    elif change == "symlink":
        target = tmp_path / "aliased.so"
        case.library.rename(target)
        case.library.symlink_to(target)
    elif change == "extra_field":
        case.manifest["unrecognised"] = "value"
    else:
        case.manifest["source_root"] = str(tmp_path / "different-release")
    case.path.write_bytes(canonical(case.manifest))
    monkeypatch.setattr(subject._native_probe, "_load_extension",
                        lambda *args: pytest.fail("Unsafe release binding must fail before loading native code"))
    with pytest.raises(ValueError):
        load(case)


@pytest.mark.parametrize("attribute,value", [("QUALITY_PROJECTION_VERSION", 1), ("QUALITY_PROJECTION_VERSION", True),
                                            ("VerifiedConfiguration", object()), ("project_quality_source", None)])
def test_wrong_extension_protocol_is_rejected(tmp_path, monkeypatch, attribute, value):
    case = write_manifest(tmp_path, monkeypatch)
    extension = FakeExtension()
    setattr(extension, attribute, value)
    monkeypatch.setattr(subject._native_probe, "_load_extension", lambda *args: extension)
    with pytest.raises(ValueError):
        load(case)


def test_decoding_shares_only_fixed_contract_keys_and_preserves_all_values():
    value = {"generation": "synthetic-value-not-a-key", "payload": {
        "energy_kwh": -0.0, "source_binding": {"schema": 1, "energy_entity_id": "sensor.synthetic"},
        "private-unbounded-json-key-0123456789": [True, None, 2**80, "ö"]}}
    encoded = canonical(value)
    before = dict(subject._SHARED_KEYS)
    first, second = [json.loads(encoded, object_pairs_hook=subject._shared_object) for _ in range(2)]
    assert canonical(first) == canonical(second) == encoded
    for key in ("generation", "payload"):
        assert next(k for k in first if k == key) is next(k for k in second if k == key)
    assert first["generation"] is not second["generation"]
    assert next(k for k in first["payload"] if k.startswith("private-")) is not next(
        k for k in second["payload"] if k.startswith("private-"))
    assert subject._SHARED_KEYS == before


def test_real_kernel_live_archive_matches_full_reference_and_uses_native_read_lock(tmp_path, monkeypatch, policy_store):
    import fcntl

    binary = os.environ.get("ADAPTIVE_SOLAR_TEST_NATIVE_QUALITY_BINARY")
    if not binary:
        pytest.skip("Explicit real native-quality binary was not requested")
    root = Path(subject.__file__).resolve().parents[1]
    library = Path(binary).resolve()
    manifest = {"schema": "adaptive-solar-native-quality-runtime-v1", "protocol_version": 2,
                "source_root": str(root),
                "sources": {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                            for name in subject.SOURCE_FILES},
                "binary": {"path": str(library.relative_to(root)),
                           "sha256": hashlib.sha256(library.read_bytes()).hexdigest()},
                "runtime": subject._runtime_snapshot()}
    path = tmp_path / "real-native-runtime.json"
    path.write_bytes(canonical(manifest))
    backend = subject.load_backend(path, hashlib.sha256(path.read_bytes()).hexdigest())
    real_lock = archive._lock
    locks = []

    @contextmanager
    def recording_lock(archive_root):
        with real_lock(archive_root):
            locks.append(archive_root)
            yield

    monkeypatch.setattr(archive, "_lock", recording_lock)
    raw = canonical(policy_store.raw)
    with (tmp_path / "writer.lock").open("a") as writer_lock:
        fcntl.flock(writer_lock, fcntl.LOCK_EX)
        expected = derive(policy_store)
        locks.clear()
        assert canonical(derive(policy_store, backend)) == canonical(expected)
        assert policy_store.store.root in locks
    assert canonical(policy_store.raw) == raw
    assert backend.stats["sources_projected"] == 1
    assert backend.stats["configuration_proofs"] == 1
    assert backend.stats["source_fallbacks"] == 0
    assert backend.stats["closed"]
