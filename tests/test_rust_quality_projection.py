"""Projection capability and fallback guards without an optional Rust binary."""
from contextlib import nullcontext
import gc
import hashlib
import json
from types import ModuleType, SimpleNamespace
import weakref

import pytest

from scripts import rust_quality_projection as subject


@pytest.fixture
def compact(tmp_path, monkeypatch):
    root = tmp_path / "source"
    path = root / "scripts/continuous_quality.py"
    path.parent.mkdir(parents=True)
    text = '''def derive(store, raw, bindings):
    byte_count = 0
    event_count = 0
    configurations = []
    def account(size, count=0):
        nonlocal byte_count, event_count
        byte_count += size
        event_count += count
        if byte_count > MAX_BYTES or event_count > 500000:
            raise ValueError('Quality selection exceeds bounded budget')
    def project(event, parts=(), *, anchor=False):
        configurations.append({'native': True})
    for event in store.iter_events(source='synthetic'):
        project(event, anchor=event['event_id'] == 'anchor')
    return configurations, byte_count, event_count
'''
    path.write_text(text)
    continuous = ModuleType("synthetic_compact")
    continuous.__file__ = str(path)
    continuous.MAX_BYTES = 512 * 1024**2
    continuous.capture_actuals = SimpleNamespace(target_bounds=lambda a, b: (
        __import__("datetime").datetime.fromisoformat(a), __import__("datetime").datetime.fromisoformat(b)))
    exec(compile(text, str(path), "exec"), continuous.__dict__)

    class Configuration:
        __slots__ = ("_canonical", "_token")

        @property
        def retained_bytes(self):
            return len(self._canonical)

    quality = SimpleNamespace(__file__=str(root / "custom_components/adaptive_solar/core/actual_quality.py"),
        CONTINUOUS_BINDINGS_SCHEMA="adaptive-solar-actual-quality-bindings-v2", MAX_EVENTS=500000,
        _ForecastConfiguration=Configuration, _CONFIGURATION_TOKEN=object())

    class Store:
        def __init__(self):
            self.root = tmp_path / "archive"

        def iter_events(self, *, source=None, kind=None, dataset=None):
            yield {"event_id": "native", "kind": "forecast_issued"}

        def _db(self):
            return nullcontext(SimpleNamespace(execute=lambda *a: SimpleNamespace(fetchall=lambda: [("a" * 64,)])))

        def _original_path(self, digest):
            return self.root / (digest + ".json.gz")

    archive = SimpleNamespace(__file__=str(root / "custom_components/adaptive_solar/core/archive.py"),
        ArchiveStore=Store, SCHEMA=1, MAX_PAGE_BYTES=4194304, MAX_EVENT_BYTES=1048576, MAX_PAGE_EVENTS=1000,
        _lock=lambda _: nullcontext(), _text=lambda *args: None)
    source_files = {**subject.COMPACT_SOURCES,
                    "custom_components/adaptive_solar/core/archive.py": next(iter(subject.native_probe.SUPPORTED_NATIVE_SOURCES))}
    monkeypatch.setattr(subject, "__file__", str(root / "scripts/rust_quality_projection.py"))
    monkeypatch.setattr(subject, "_sources", lambda _: dict(source_files))

    class OpaqueConfiguration:
        def __init__(self):
            self.configuration_bytes = b'{"anchor_site":{}}'
            self.original_full_working_size = 128
            self.anchor = True

        def __getitem__(self, key):
            return {"event_id": "anchor", "kind": "forecast_issued"}[key]

    class Items:
        def __init__(self, items):
            self.pending = list(items)

        def __len__(self):
            return len(self.pending)

        def __iter__(self):
            return self

        def __next__(self):
            if not self.pending:
                raise StopIteration
            return self.pending.pop(0)

    class Source:
        def __init__(self, paths, query):
            self.source = query["source"]
            self.query_sha256 = subject._digest(query)
            self.bindings_sha256 = query["bindings_sha256"]
            self.original_files, self.original_events, self.selected_events = len(paths), 3, 1
            self.item = OpaqueConfiguration()

        def items(self):
            return (self.item,)

        def take_items(self):
            return Items(self.items())

    extension = SimpleNamespace(QUALITY_PROJECTION_VERSION=2, VerifiedConfiguration=OpaqueConfiguration,
        VerifiedQualityItems=Items,
        VerifiedQualitySource=Source, project_quality_source=lambda paths, query, **kwargs: Source(paths, json.loads(query)))
    monkeypatch.setattr(subject.native_probe, "_load_extension", lambda *args: extension)
    module = tmp_path / "synthetic.so"
    module.write_bytes(b"synthetic; never loaded")
    sha = hashlib.sha256(module.read_bytes()).hexdigest()
    raw = {"raw": {"target_start": "2026-01-01T00:00:00+00:00", "target_end": "2026-01-02T00:00:00+00:00"}}
    bindings = {"schema": quality.CONTINUOUS_BINDINGS_SCHEMA, "bindings": [{"source": "synthetic",
        "valid_from": raw["raw"]["target_start"], "valid_to": raw["raw"]["target_end"], "config_event_id": "anchor"}]}
    return SimpleNamespace(archive=archive, continuous=continuous, quality=quality, extension=extension,
        module=module, sha=sha, raw=raw, bindings=bindings, source_files=source_files, root=root)


def scope(case):
    return subject.projected_quality_reader(case.archive, case.continuous, case.quality,
                                            case.module, case.sha, case.raw, case.bindings)


def test_individual_decodes_share_fixed_contract_keys_and_preserve_all_values():
    value = {"generation": "synthetic-value-not-a-key", "payload": {
        "energy_kwh": -0.0, "source_binding": {"schema": 1, "energy_entity_id": "sensor.synthetic"},
        "private-unknown-json-key-synthetic-12345": [True, None, 2**80, "ö"]}}
    encoded = subject._canonical(value)
    before = dict(subject._SHARED_KEYS)
    first, second = [json.loads(encoded, object_pairs_hook=subject._shared_object) for _ in range(2)]
    assert subject._canonical(first) == subject._canonical(second) == encoded
    for name in ("generation", "payload"):
        assert next(k for k in first if k == name) is next(k for k in second if k == name)
    assert next(k for k in first["payload"] if k == "energy_kwh") is next(k for k in second["payload"] if k == "energy_kwh")
    # Neither private values nor an unbounded vocabulary are placed in the pool.
    assert first["generation"] is not second["generation"]
    assert next(k for k in first["payload"] if k.startswith("private-")) is not next(
        k for k in second["payload"] if k.startswith("private-"))
    assert subject._SHARED_KEYS == before


def test_scoped_registry_does_not_retain_skipped_native_configurations(compact):
    c = compact
    with scope(c):
        values = list(c.archive.ArchiveStore().iter_events(source="synthetic"))
        reference = weakref.ref(values[0])
        del values
        gc.collect()
        assert reference() is None


def test_opaque_factory_uses_original_working_size_and_restores_functions(compact):
    c = compact
    original_iter, original_derive = c.archive.ArchiveStore.iter_events, c.continuous.derive
    with scope(c) as stats:
        proofs, byte_count, count = c.continuous.derive(c.archive.ArchiveStore(), c.raw, c.bindings)
        assert len(proofs) == count == 1
        assert type(proofs[0]) is c.quality._ForecastConfiguration
        assert proofs[0]._token is c.quality._CONFIGURATION_TOKEN
        assert byte_count == len(b'{"anchor_site":{}}')
        assert stats["configuration_proofs"] == 1
    assert stats["closed"] and stats["original_files"] == 1 and stats["original_events"] == 3
    assert c.archive.ArchiveStore.iter_events is original_iter and c.continuous.derive is original_derive
    assert not any(key.startswith(("__rust_is_config_", "__rust_promote_")) for key in vars(c.continuous))


def test_working_budget_is_not_replaced_by_short_proof_size(compact):
    c = compact
    c.continuous.MAX_BYTES = 64
    with scope(c):
        with pytest.raises(ValueError, match="bounded budget"):
            c.continuous.derive(c.archive.ArchiveStore(), c.raw, c.bindings)


def test_unsupported_source_returns_original_generator_without_a_yield_wrapper(compact):
    c = compact
    c.extension.project_quality_source = lambda *args, **kwargs: None
    original = c.archive.ArchiveStore.iter_events
    with scope(c) as stats:
        iterator = c.archive.ArchiveStore().iter_events(source="synthetic")
        assert iterator.gi_code is original.__code__
        assert list(iterator) == [{"event_id": "native", "kind": "forecast_issued"}]
    assert stats["sources_projected"] == 0 and stats["source_fallbacks"] == 1


def test_custom_reader_method_keeps_its_native_generator(compact):
    c = compact

    class CustomReader(c.archive.ArchiveStore):
        def _original_path(self, digest):
            raise AssertionError("Native generator in this synthetic case does not read paths")

    original = c.archive.ArchiveStore.iter_events
    with scope(c) as stats:
        iterator = CustomReader().iter_events(source="synthetic")
        assert iterator.gi_code is original.__code__
        assert list(iterator) == [{"event_id": "native", "kind": "forecast_issued"}]
    assert stats["fallback_reasons"] == {"custom_reader": 1}


def test_wrong_query_never_exposes_partial_items(compact):
    c = compact
    factory = c.extension.project_quality_source

    def wrong(*args, **kwargs):
        result = factory(*args, **kwargs)
        result.query_sha256 = "f" * 64
        return result

    c.extension.project_quality_source = wrong
    with scope(c):
        with pytest.raises(ValueError, match="binding mismatch"):
            c.archive.ArchiveStore().iter_events(source="synthetic")


def test_external_opaque_of_same_type_is_not_a_scoped_capability(compact):
    c = compact
    with scope(c):
        list(c.archive.ArchiveStore().iter_events(source="synthetic"))
        promote = next(value for name, value in vars(c.continuous).items() if name.startswith("__rust_promote_"))
        with pytest.raises(ValueError, match="scoped"):
            promote(c.extension.VerifiedConfiguration(), True)


@pytest.mark.parametrize("change", ["policy", "raw", "source"])
def test_input_mutation_invalidates_closing_scope(compact, change):
    c = compact
    with pytest.raises(ValueError, match="changed"):
        with scope(c):
            if change == "policy":
                c.bindings["bindings"][0]["config_event_id"] = "changed"
            elif change == "raw":
                c.raw["capture_id"] = "changed"
            else:
                c.source_files["scripts/replay.py"] = "changed"


def test_legacy_consumer_is_explicitly_unsupported(compact):
    c = compact
    c.source_files["scripts/continuous_quality.py"] = "legacy"
    with pytest.raises(ValueError, match="qualified compact"):
        with scope(c):
            pytest.fail("Legacy must not receive opaque configuration objects")
