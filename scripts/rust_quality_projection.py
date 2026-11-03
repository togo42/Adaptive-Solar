"""Frozen-source experiment: native selection and opaque configuration proofs.

Only the explicitly qualified compact consumer is supported. The legacy
consumer and normal archive operation are unchanged. Unsupported source reads
return the original native generator; no partial projection is published.
"""
from __future__ import annotations

import ast
from contextlib import contextmanager
import hashlib
import inspect
import json
from pathlib import Path
import sys
import textwrap
import types
from uuid import uuid4
from weakref import WeakValueDictionary

from scripts import rust_archive_probe as native_probe

COMPACT_SOURCES = {
    "scripts/continuous_quality.py": "f98779199a443d4d97466ee6d9d4ca3922fed977ba745be77d11703036a9c543",
    "custom_components/adaptive_solar/core/actual_quality.py": "27d5929efca61383470054a232fb1de7c65460c3e154275b4936563ea2570ef6",
    "scripts/capture_actuals.py": "50058b837b1d30eb09c4fea33b2ff407c6db1610a3eab3dec7c73f373a214c7e",
    "scripts/actual_quality_io.py": "17e7583b90edf95f49bda1754e4429822b7ad81afc52308f46020e6144f0309c",
}

# A native page decode shares equal object keys within that page. Individual
# projected-event decodes would otherwise retain a fresh copy of these keys
# for every interval. Share only this fixed contract vocabulary; never intern
# arbitrary input keys, values or private identifiers globally.
_SHARED_KEYS = types.MappingProxyType({key: key for key in (
    "schema", "source", "generation", "sequence", "event_id", "kind", "received_at", "payload", "sha256",
    "inverter_id", "start", "end", "observed_at", "energy_kwh", "measurement_contract", "continuity_id",
    "boundary_reason", "curtailment_measurement_contract", "source_binding", "energy_entity_id",
    "config_sha256", "producer_sha256",
)})


def _shared_object(pairs):
    return {_SHARED_KEYS.get(key, key): value for key, value in pairs}


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sources(root):
    paths = [*root.iterdir()]
    for name in ("custom_components", "scripts"):
        paths.extend((root / name).rglob("*"))
    result, total = {}, 0
    for path in paths:
        if path.is_symlink() or path.name == "__pycache__" or path.suffix in {".pyc", ".pyo"}:
            raise ValueError("Projection sources must be canonical, cache-free files")
        if path.is_file() and path.suffix in {".py", ".json"}:
            total += path.stat().st_size
            if len(result) >= 2000 or total > 128 * 1024**2:
                raise ValueError("Projection source inventory exceeds budget")
            result[str(path.relative_to(root))] = native_probe._file_sha(path)
    return result


def _derive_hook(original, module, is_name, promote_name):
    """Keep the original derive/project frames and every native statement."""
    if (not inspect.isfunction(original) or original.__closure__
            or original.__globals__ is not module.__dict__
            or Path(original.__code__.co_filename).resolve() != Path(module.__file__).resolve()):
        raise ValueError("Projection requires the original compact derive function")
    lines, first = inspect.getsourcelines(original)
    tree = ast.parse(textwrap.dedent("".join(lines)))
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef) or tree.body[0].name != "derive":
        raise ValueError("Unsupported compact derive source")
    outer = tree.body[0]
    projects = [node for node in outer.body if isinstance(node, ast.FunctionDef) and node.name == "project"]
    if len(projects) != 1:
        raise ValueError("Unsupported compact projection factory source")
    project = projects[0]
    if [arg.arg for arg in project.args.args] != ["event", "parts"] or [a.arg for a in project.args.kwonlyargs] != ["anchor"]:
        raise ValueError("Unsupported compact projection factory signature")
    original_ast = ast.dump(tree, include_attributes=False)
    variable = "_native_projection_proof_" + uuid4().hex
    branch = ast.parse(f"""
if {is_name}(event):
    if parts:
        raise ValueError('Opaque inline evidence cannot accept dependency arguments')
    if byte_count + event.original_full_working_size > MAX_BYTES:
        raise ValueError('Quality selection exceeds bounded budget')
    {variable} = {promote_name}(event, anchor)
    account({variable}.retained_bytes, 1)
    configurations.append({variable})
    return
""").body
    project.body[0:0] = branch
    del project.body[:len(branch)]
    if ast.dump(tree, include_attributes=False) != original_ast:
        raise ValueError("Projection changed native derive statements")
    project.body[0:0] = branch
    ast.fix_missing_locations(tree)
    ast.increment_lineno(tree, first - 1)
    # Extract only the function code: compiling the enclosing definition must
    # not evaluate native defaults, decorators or annotations a second time.
    code = compile(tree, module.__file__, "exec", dont_inherit=True)
    function_code = next(value for value in code.co_consts
                         if isinstance(value, types.CodeType) and value.co_name == "derive")
    replacement = types.FunctionType(function_code, original.__globals__, original.__name__,
                                     original.__defaults__, original.__closure__)
    replacement.__kwdefaults__ = original.__kwdefaults__
    replacement.__qualname__, replacement.__module__ = original.__qualname__, original.__module__
    return replacement, hashlib.sha256(original_ast.encode()).hexdigest()


@contextmanager
def projected_quality_reader(archive, continuous, quality, module_path, expected_sha256, raw, bindings):
    """Install one bounded frozen-corpus experiment, never a production cache.

    Caller must supply the same frozen archive and complete input inventories
    before and after the scope, as profile_quality does. All original batches
    of each queried source are still natively validated on every read.
    """
    root = Path(archive.__file__).resolve().parents[3]
    if (root != Path(__file__).resolve().parents[1]
            or Path(continuous.__file__).resolve() != root / "scripts/continuous_quality.py"
            or Path(quality.__file__).resolve() != root / "custom_components/adaptive_solar/core/actual_quality.py"):
        raise ValueError("Projection modules must share the pinned source root")
    before = _sources(root)
    if any(before.get(name) != sha for name, sha in COMPACT_SOURCES.items()):
        raise ValueError("Native projection requires the qualified compact consumer; legacy remains unchanged")
    if (before.get("custom_components/adaptive_solar/core/archive.py") not in native_probe.SUPPORTED_NATIVE_SOURCES
            or archive.SCHEMA != 1 or sys.implementation.name != "cpython" or sys.version_info[:2] != (3, 14)):
        raise ValueError("Unsupported native projection reader or runtime")
    path = Path(module_path).absolute()
    if (path.is_symlink() or path.resolve() != path or not path.is_file()
            or not 0 < path.stat().st_size <= 128 * 1024**2
            or native_probe._file_sha(path) != expected_sha256):
        raise ValueError("Projection binary pin mismatch")
    extension = native_probe._load_extension(path, expected_sha256)
    if (getattr(extension, "QUALITY_PROJECTION_VERSION", None) != 2
            or not callable(getattr(extension, "project_quality_source", None))
            or not isinstance(getattr(extension, "VerifiedConfiguration", None), type)
            or not isinstance(getattr(extension, "VerifiedQualitySource", None), type)
            or not isinstance(getattr(extension, "VerifiedQualityItems", None), type)):
        raise ValueError("Unsupported native quality projection protocol")
    if bindings.get("schema") != quality.CONTINUOUS_BINDINGS_SCHEMA:
        raise ValueError("Projection requires the complete continuous binding policy")
    start, end = continuous.capture_actuals.target_bounds(raw["raw"]["target_start"], raw["raw"]["target_end"])
    policy_hash, raw_hash = _digest(bindings), _digest(raw)
    sources = sorted({row["source"] for row in bindings["bindings"]})
    queries = {source: dict(schema=1, source=source, target_start=start.isoformat(), target_end=end.isoformat(),
                           periods=[{key: row[key] for key in ("valid_from", "valid_to", "config_event_id")}
                                    for row in bindings["bindings"] if row["source"] == source],
                           bindings_sha256=policy_hash) for source in sources}
    runtime = native_probe._runtime(archive)
    stats = dict(closed=False, protocol_version=2, binary_sha256=expected_sha256,
                 source_manifest_sha256=_digest(before), bindings_sha256=policy_hash,
                 raw_sha256=raw_hash, sources_projected=0, source_fallbacks=0, fallback_reasons={},
                 original_files=0, original_events=0, selected_events=0, configuration_proofs=0)
    native_iter, native_derive = archive.ArchiveStore.iter_events, continuous.derive
    native_reader_methods = tuple(name for name in ("_read_original", "_original_path", "_read_lock")
                                  if hasattr(archive.ArchiveStore, name))
    eligible = WeakValueDictionary()

    def fallback(reason, reader, **options):
        stats["source_fallbacks"] += 1
        stats["fallback_reasons"][reason] = stats["fallback_reasons"].get(reason, 0) + 1
        return native_iter(reader, **options)

    def is_configuration(item):
        return type(item) is extension.VerifiedConfiguration

    def promote(item, anchor):
        if (not is_configuration(item) or eligible.get(id(item)) is not item
                or type(anchor) is not bool or item.anchor is not anchor):
            raise ValueError("Configuration evidence must be native, scoped and anchor-bound")
        canonical = item.configuration_bytes
        if type(canonical) is not bytes or len(canonical) > continuous.MAX_BYTES:
            raise ValueError("Invalid opaque configuration evidence")
        proof = object.__new__(quality._ForecastConfiguration)
        object.__setattr__(proof, "_canonical", canonical)
        object.__setattr__(proof, "_token", quality._CONFIGURATION_TOKEN)
        stats["configuration_proofs"] += 1
        return proof

    def decode(item):
        if is_configuration(item):
            eligible[id(item)] = item
            return item
        if type(item) is not bytes:
            raise ValueError("Unexpected native projection item")
        return json.loads(item, object_pairs_hook=_shared_object)

    def iterate(reader, *, source=None, kind=None, dataset=None):
        options = dict(source=source, kind=kind, dataset=dataset)
        if any(name in vars(reader) or getattr(getattr(reader, name, None), "__func__", None)
               is not getattr(archive.ArchiveStore, name) for name in native_reader_methods):
            return fallback("custom_reader", reader, **options)
        if source not in queries or kind is not None or dataset is not None:
            return fallback("unsupported_query", reader, **options)
        if native_probe._headroom() < native_probe.MIN_HEADROOM or native_probe._runtime(archive) != runtime:
            return fallback("runtime_or_headroom", reader, **options)
        archive._text(source, "source")
        query = queries[source]
        # Preserve exactly the native SQL order and its complete same-source
        # batch set. A malformed index hint never becomes an exclusion proof.
        lock = reader._read_lock(source=source) if hasattr(reader, "_read_lock") else archive._lock(reader.root)
        with lock, reader._db() as connection:
            rows = connection.execute("SELECT hash FROM batches WHERE (? IS NULL OR source=?) ORDER BY ingest_order,hash",
                                      (source, source)).fetchall()
            paths = [str(reader._original_path(digest)) for (digest,) in rows]
            result = extension.project_quality_source(paths, _canonical(query), max_page_bytes=archive.MAX_PAGE_BYTES,
                max_event_bytes=archive.MAX_EVENT_BYTES, max_page_events=archive.MAX_PAGE_EVENTS, max_depth=64,
                max_retained_bytes=continuous.MAX_BYTES, max_selected_events=quality.MAX_EVENTS)
        if result is None:
            return fallback("unsupported_source", reader, **options)
        if (type(result) is not extension.VerifiedQualitySource or result.source != source
                or result.bindings_sha256 != policy_hash or result.query_sha256 != _digest(query)
                or result.original_files != len(paths)):
            raise ValueError("Native projection query or corpus binding mismatch")
        items = result.take_items()
        if type(items) is not extension.VerifiedQualityItems or len(items) != result.selected_events:
            raise ValueError("Native projection item count mismatch")
        stats["sources_projected"] += 1
        for name in ("original_files", "original_events", "selected_events"):
            stats[name] += getattr(result, name)
        return map(decode, items)

    token = uuid4().hex
    is_name, promote_name = "__rust_is_config_" + token, "__rust_promote_" + token
    replacement, ast_hash = _derive_hook(native_derive, continuous, is_name, promote_name)
    stats["native_derive_ast_sha256"] = ast_hash
    continuous.__dict__[is_name], continuous.__dict__[promote_name] = is_configuration, promote
    archive.ArchiveStore.iter_events, continuous.derive = iterate, replacement
    try:
        yield stats
    finally:
        changed = archive.ArchiveStore.iter_events is not iterate or continuous.derive is not replacement
        archive.ArchiveStore.iter_events, continuous.derive = native_iter, native_derive
        continuous.__dict__.pop(is_name, None)
        continuous.__dict__.pop(promote_name, None)
        stats["closed"] = True
        eligible.clear()
        if (changed or _sources(root) != before or native_probe._runtime(archive) != runtime
                or native_probe._file_sha(path) != expected_sha256 or _digest(bindings) != policy_hash
                or _digest(raw) != raw_hash):
            raise ValueError("Native projection scope sources, inputs, runtime or instrumentation changed")
