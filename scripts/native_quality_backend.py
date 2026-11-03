"""Explicit, pinned Rust selection for the archive host's quality worker.

The default consumer remains Python. This backend never patches functions or
classes and does not treat a serializable document as verified source evidence.
The caller holds the host writer lock or supplies an immutable archive copy.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import importlib.metadata
import json
from pathlib import Path, PurePosixPath
import re
import sys
import sysconfig
import types
from weakref import WeakValueDictionary

from custom_components.adaptive_solar.core import actual_quality as _quality
from custom_components.adaptive_solar.core import archive as _archive
from scripts import capture_actuals
from scripts import rust_archive_probe as _native_probe

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "adaptive-solar-native-quality-runtime-v1"
STATUS_SCHEMA = "adaptive-solar-native-quality-runtime-status-v1"
SOURCE_FILES = frozenset({
    "scripts/native_quality_backend.py", "scripts/rust_archive_probe.py", "scripts/continuous_quality.py",
    "scripts/capture_actuals.py", "scripts/actual_quality_io.py", "scripts/archive_observations.py",
    "scripts/archive_host.py", "custom_components/adaptive_solar/core/archive.py",
    "custom_components/adaptive_solar/core/actual_quality.py",
})
DEPENDENCIES = ("pvlib", "scikit-learn", "numpy", "pandas", "aiohttp")
SUPPORTED_FACTORY_SOURCES = frozenset({
    "27d5929efca61383470054a232fb1de7c65460c3e154275b4936563ea2570ef6",
    "cd230e944b3fa7d2ec3be4e11be3933b5baae79ff873c8460f83c2b9ad860e6e",
})
SUPPORTED_ARCHIVE_SOURCES = frozenset({
    "2788a9e113dd80a348a6d70c1be055e7ae97509046592a93cad2a8fa73694660",
    "eadc990a6269fc2258416b9e1f14cf61c976cd0ed247084cb7e74a0beb8dc03f",
})
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_SHARED_KEYS = types.MappingProxyType({key: key for key in (
    "schema", "source", "generation", "sequence", "event_id", "kind", "received_at", "payload", "sha256",
    "inverter_id", "start", "end", "observed_at", "energy_kwh", "measurement_contract", "continuity_id",
    "boundary_reason", "curtailment_measurement_contract", "source_binding", "energy_entity_id",
    "config_sha256", "producer_sha256",
)})


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _hash(value):
    return isinstance(value, str) and _HEX.fullmatch(value) is not None


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate native runtime manifest field")
        result[key] = value
    return result


def _shared_object(pairs):
    return {_SHARED_KEYS.get(key, key): value for key, value in pairs}


def _runtime_snapshot():
    return {
        "implementation": sys.implementation.name, "version": sys.version,
        "soabi": sysconfig.get_config_var("SOABI"),
        "gil_disabled": int(sysconfig.get_config_var("Py_GIL_DISABLED") or 0),
        "python_binary_sha256": _native_probe._file_sha(Path(sys.executable).resolve()),
        "dependencies": {name: importlib.metadata.version(name) for name in DEPENDENCIES},
    }


def _validate_module_origins(root):
    modules = {
        "custom_components/adaptive_solar/core/archive.py": _archive,
        "custom_components/adaptive_solar/core/actual_quality.py": _quality,
        "scripts/rust_archive_probe.py": _native_probe,
        "scripts/capture_actuals.py": capture_actuals,
    }
    for name in SOURCE_FILES:
        module = sys.modules.get(name.removesuffix(".py").replace("/", "."))
        if module is not None:
            modules[name] = module
    if any(Path(getattr(module, "__file__", "")).resolve() != root / name for name, module in modules.items()):
        raise ValueError("Native quality modules do not share the pinned source root")


def _member(root, name):
    if (not isinstance(name, str) or not name or len(name) > 4096
            or PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts
            or str(PurePosixPath(name)) != name):
        raise ValueError("Invalid native runtime member path")
    path = root / name
    if path.is_symlink() or path.resolve() != path or not path.is_file():
        raise ValueError("Native runtime member must be a canonical regular file")
    return path


def load_backend(manifest_path, expected_sha256):
    """Load one explicitly requested backend; configuration errors fail closed."""
    if not _hash(expected_sha256):
        raise ValueError("An external native runtime manifest hash is required")
    manifest = Path(manifest_path).absolute()
    if manifest.is_symlink() or not manifest.is_file() or not 0 < manifest.stat().st_size <= 1024**2:
        raise ValueError("Invalid native runtime manifest file")
    raw = manifest.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("Native runtime manifest hash mismatch")
    data = json.loads(raw, object_pairs_hook=_unique_object)
    if (not isinstance(data, dict) or set(data) != {
            "schema", "protocol_version", "source_root", "sources", "binary", "runtime"}
            or data["schema"] != SCHEMA or type(data["protocol_version"]) is not int
            or data["protocol_version"] != 2):
        raise ValueError("Unsupported native runtime manifest schema")
    root = Path(ROOT).resolve()
    if not isinstance(data["source_root"], str) or data["source_root"] != str(root):
        raise ValueError("Native runtime release root mismatch")
    sources = data["sources"]
    binary = data["binary"]
    runtime = data["runtime"]
    if (not isinstance(sources, dict) or set(sources) != SOURCE_FILES
            or any(not _hash(value) for value in sources.values())):
        raise ValueError("Incomplete native runtime source pins")
    if (not isinstance(binary, dict) or set(binary) != {"path", "sha256"}
            or not _hash(binary["sha256"]) or not isinstance(binary["path"], str)
            or not binary["path"].endswith(".so")):
        raise ValueError("Invalid native runtime binary pin")
    if (not isinstance(runtime, dict) or set(runtime) != {
            "implementation", "version", "soabi", "gil_disabled", "python_binary_sha256", "dependencies"}
            or type(runtime["gil_disabled"]) is not int or not _hash(runtime["python_binary_sha256"])
            or not isinstance(runtime["dependencies"], dict)
            or set(runtime["dependencies"]) != set(DEPENDENCIES)
            or any(not isinstance(value, str) or not value for value in runtime["dependencies"].values())):
        raise ValueError("Incomplete native runtime interpreter pins")
    if (sys.implementation.name != "cpython" or sys.version_info[:2] != (3, 14)
            or int(sysconfig.get_config_var("Py_GIL_DISABLED") or 0) != 0):
        raise ValueError("Native quality selection requires CPython 3.14 with the GIL")
    backend = RustQualityBackend(root, manifest, expected_sha256, data)
    backend._check_current()
    extension = _native_probe._load_extension(backend.binary, binary["sha256"])
    if (type(getattr(extension, "PROTOCOL_VERSION", None)) is not int or extension.PROTOCOL_VERSION != 1
            or type(getattr(extension, "QUALITY_PROJECTION_VERSION", None)) is not int
            or extension.QUALITY_PROJECTION_VERSION != 2
            or not callable(getattr(extension, "project_quality_source", None))
            or any(not isinstance(getattr(extension, name, None), type) for name in
                   ("VerifiedConfiguration", "VerifiedQualitySource", "VerifiedQualityItems"))):
        raise ValueError("Unsupported native quality projection protocol")
    backend.extension = extension
    return backend


class RustQualityBackend:
    """Immutable activation pins with independent, per-derivation sessions."""

    def __init__(self, root, manifest, manifest_sha256, data):
        self.root, self.manifest, self.manifest_sha256 = root, manifest, manifest_sha256
        self._data = deepcopy(data)
        self.binary = _member(root, data["binary"]["path"])
        self.extension = None
        self._last_stats = None

    @property
    def stats(self):
        return deepcopy(self._last_stats)

    def _check_current(self):
        if (self.manifest.is_symlink() or _native_probe._file_sha(self.manifest) != self.manifest_sha256
                or _runtime_snapshot() != self._data["runtime"]):
            raise ValueError("Native runtime manifest or interpreter changed")
        _validate_module_origins(self.root)
        for name, expected in self._data["sources"].items():
            path = _member(self.root, name)
            if path.stat().st_size > 128 * 1024**2 or _native_probe._file_sha(path) != expected:
                raise ValueError("Native runtime source pin mismatch")
        binary = _member(self.root, self._data["binary"]["path"])
        if (binary != self.binary or not 0 < binary.stat().st_size <= 128 * 1024**2
                or _native_probe._file_sha(binary) != self._data["binary"]["sha256"]):
            raise ValueError("Native runtime binary pin mismatch")
        archive_hash = self._data["sources"]["custom_components/adaptive_solar/core/archive.py"]
        if (archive_hash not in SUPPORTED_ARCHIVE_SOURCES
                or archive_hash not in _native_probe.SUPPORTED_NATIVE_SOURCES or _archive.SCHEMA != 1):
            raise ValueError("Unqualified native archive source or schema")
        if (self._data["sources"]["custom_components/adaptive_solar/core/actual_quality.py"]
                not in SUPPORTED_FACTORY_SOURCES):
            raise ValueError("Unqualified native configuration factory")

    @contextmanager
    def bind(self, store, raw, bindings):
        self._last_stats = None
        self._check_current()
        session = NativeQualitySession(self, store, raw, bindings)
        try:
            yield session
        finally:
            try:
                session._finish()
            finally:
                self._last_stats = session.stats


class _ProjectedIterator:
    def __init__(self, session, native):
        self.session, self.native, self.closed = session, native, False

    def __iter__(self):
        return self

    def __next__(self):
        if self.closed:
            raise StopIteration
        self.session._check_open()
        try:
            item = next(self.native)
            return self.session._decode(item)
        except BaseException:
            self.close()
            raise

    def close(self):
        if not self.closed:
            self.closed = True
            native, session = self.native, self.session
            self.native = self.session = None
            session._iterators.pop(id(self), None)
            close = getattr(native, "close", None)
            if close is not None:
                close()


class NativeQualitySession:
    def __init__(self, backend, store, raw, bindings):
        if not isinstance(store, _archive.ArchiveStore):
            raise ValueError("Native quality selection requires an archive store")
        if not isinstance(bindings, dict) or bindings.get("schema") != _quality.CONTINUOUS_BINDINGS_SCHEMA:
            raise ValueError("Native quality selection requires complete continuous bindings")
        self.backend, self.store, self.raw, self.bindings = backend, store, raw, bindings
        self.extension = backend.extension
        self._policy_hash, self._raw_hash = _digest(bindings), _digest(raw)
        self._reader_runtime = _native_probe._runtime(_archive)
        start, end = capture_actuals.target_bounds(raw["raw"]["target_start"], raw["raw"]["target_end"])
        rows = bindings["bindings"]
        self.queries = {
            source: dict(schema=1, source=source, target_start=start.isoformat(), target_end=end.isoformat(),
                         periods=[{key: row[key] for key in ("valid_from", "valid_to", "config_event_id")}
                                  for row in rows if row["source"] == source],
                         bindings_sha256=self._policy_hash)
            for source in sorted({row["source"] for row in rows})
        }
        self._eligible = WeakValueDictionary()
        self._iterators = {}
        self._closed = False
        self._stats = dict(schema=STATUS_SCHEMA, requested_backend="rust", effective_backend="not_used",
                           protocol_version=2, closed=False, sources_projected=0, source_fallbacks=0,
                           fallback_reasons={}, original_files=0, original_events=0, selected_events=0,
                           configuration_proofs=0, binary_sha256=backend._data["binary"]["sha256"],
                           manifest_sha256=backend.manifest_sha256,
                           source_manifest_sha256=_digest(backend._data["sources"]))

    @property
    def stats(self):
        return deepcopy(self._stats)

    def _check_open(self):
        if self._closed:
            raise ValueError("Native quality selection session is closed")

    def is_configuration(self, item):
        self._check_open()
        return type(item) is self.extension.VerifiedConfiguration

    def promote_configuration(self, item, *, anchor=False):
        self._check_open()
        if (not self.is_configuration(item) or self._eligible.get(id(item)) is not item
                or type(anchor) is not bool or item.anchor is not anchor):
            raise ValueError("Configuration evidence must be native, scoped and anchor-bound")
        canonical = item.configuration_bytes
        if type(canonical) is not bytes or len(canonical) > 512 * 1024**2:
            raise ValueError("Invalid opaque configuration evidence")
        proof = object.__new__(_quality._ForecastConfiguration)
        object.__setattr__(proof, "_canonical", canonical)
        object.__setattr__(proof, "_token", _quality._CONFIGURATION_TOKEN)
        self._stats["configuration_proofs"] += 1
        return proof

    def _decode(self, item):
        if self.is_configuration(item):
            self._eligible[id(item)] = item
            return item
        if type(item) is not bytes:
            raise ValueError("Unexpected native projection item")
        return json.loads(item, object_pairs_hook=_shared_object)

    def _fallback(self, reason, options):
        self._stats["source_fallbacks"] += 1
        reasons = self._stats["fallback_reasons"]
        reasons[reason] = reasons.get(reason, 0) + 1
        if not self._stats["sources_projected"]:
            self._stats["effective_backend"] = "python"
        iterator = iter(self.store.iter_events(**{key: value for key, value in options.items() if value is not None}))
        self._iterators[id(iterator)] = iterator
        return iterator

    def iter_events(self, *, source=None, kind=None, dataset=None):
        self._check_open()
        options = dict(source=source, kind=kind, dataset=dataset)
        for name in ("iter_events", "_read_original", "_original_path", "_read_lock", "_event_batches"):
            if (name in vars(self.store)
                    or getattr(getattr(self.store, name, None), "__func__", None)
                    is not getattr(_archive.ArchiveStore, name)):
                return self._fallback("custom_reader", options)
        if source not in self.queries or kind is not None or dataset is not None:
            return self._fallback("unsupported_query", options)
        if (_native_probe._headroom() < _native_probe.MIN_HEADROOM
                or _native_probe._runtime(_archive) != self._reader_runtime):
            return self._fallback("runtime_or_headroom", options)
        _archive._text(source, "source")
        query = self.queries[source]
        with self.store._read_lock(source=source), self.store._db() as connection:
            rows = self.store._event_batches(connection, source)
            paths = [str(self.store._original_path(digest)) for (digest,) in rows]
            result = self.extension.project_quality_source(
                paths, _canonical(query), max_page_bytes=_archive.MAX_PAGE_BYTES,
                max_event_bytes=_archive.MAX_EVENT_BYTES, max_page_events=_archive.MAX_PAGE_EVENTS,
                max_depth=64, max_retained_bytes=512 * 1024**2, max_selected_events=_quality.MAX_EVENTS)
        if result is None:
            return self._fallback("unsupported_source", options)
        if (type(result) is not self.extension.VerifiedQualitySource or result.source != source
                or result.bindings_sha256 != self._policy_hash or result.query_sha256 != _digest(query)
                or result.original_files != len(paths)):
            raise ValueError("Native projection query or corpus binding mismatch")
        items = result.take_items()
        if type(items) is not self.extension.VerifiedQualityItems or len(items) != result.selected_events:
            raise ValueError("Native projection item count mismatch")
        self._stats["sources_projected"] += 1
        self._stats["effective_backend"] = "rust"
        for name in ("original_files", "original_events", "selected_events"):
            self._stats[name] += getattr(result, name)
        iterator = _ProjectedIterator(self, items)
        self._iterators[id(iterator)] = iterator
        return iterator

    def _finish(self):
        try:
            for iterator in tuple(self._iterators.values()):
                close = getattr(iterator, "close", None)
                if close is not None:
                    close()
            self.backend._check_current()
            if (_native_probe._runtime(_archive) != self._reader_runtime
                    or _digest(self.bindings) != self._policy_hash or _digest(self.raw) != self._raw_hash):
                raise ValueError("Native selection runtime or inputs changed")
        finally:
            self._eligible.clear()
            self._iterators.clear()
            self._closed = self._stats["closed"] = True
