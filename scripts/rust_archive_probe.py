"""Optional, hash-pinned host experiment with frame-preserving native fallback.

No HA dependency or installation. A Rust result is usable only for the bounded
supported subset; all other cases execute the unchanged native reader body.
"""
from __future__ import annotations

import ast
from contextlib import contextmanager
import hashlib
import importlib.util
from importlib.machinery import ExtensionFileLoader
import inspect
import json
import marshal
from pathlib import Path
import sys
import textwrap
from uuid import uuid4

_MODULE_NAME = "_archive_probe"
_LOADED = {}
MIN_HEADROOM = 256
# Rust's native-equivalence claim covers exactly these reviewed Python readers.
# New source semantics need a fresh differential gate before extending this set.
SUPPORTED_NATIVE_SOURCES = frozenset({
    "c674f34282b48ab2609b2fb37e33ff478e1d027cee8bff7180f88f3f9f46f421",
    "2788a9e113dd80a348a6d70c1be055e7ae97509046592a93cad2a8fa73694660",
    "eadc990a6269fc2258416b9e1f14cf61c976cd0ed247084cb7e74a0beb8dc03f",
})


def _file_sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _headroom():
    depth, frame = 0, sys._getframe()
    while frame:
        depth += 1
        frame = frame.f_back
    return sys.getrecursionlimit() - depth


def _runtime(archive):
    return dict(python=sys.version, recursion_limit=sys.getrecursionlimit(),
                int_max_str_digits=sys.get_int_max_str_digits(),
                limits={key: getattr(archive, key) for key in
                        ("SCHEMA", "MAX_PAGE_BYTES", "MAX_EVENT_BYTES", "MAX_PAGE_EVENTS")})


def _load_extension(path, expected):
    """Do not relabel an already loaded binary after on-disk replacement."""
    key = str(path)
    previous = _LOADED.get(key)
    if previous is not None and previous != expected:
        raise ValueError("Restart the probe process before changing its loaded binary")
    existing = sys.modules.get(_MODULE_NAME)
    if existing is not None:
        if (Path(existing.__file__).resolve() != path
                or getattr(existing, "__archive_probe_binary_sha256__", None) != expected):
            raise ValueError("An unpinned or different archive probe is already loaded")
        return existing
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, path)
    if spec is None or not isinstance(spec.loader, ExtensionFileLoader):
        raise ValueError("Unable to load the pinned archive probe extension")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "read_original", None)):
        raise ValueError("Archive probe extension has no supported entrypoint")
    module.__archive_probe_binary_sha256__ = expected
    sys.modules[_MODULE_NAME] = module
    _LOADED[key] = expected
    return module


def _trampoline(original, archive, bridge_name):
    if (not inspect.isfunction(original) or original.__closure__
            or original.__globals__ is not archive.__dict__
            or Path(original.__code__.co_filename).resolve() != Path(archive.__file__).resolve()
            or getattr(original, "__rust_original_reader__", False)):
        raise ValueError("Rust probe requires the unwrapped native original reader")
    lines, first = inspect.getsourcelines(original)
    tree = ast.parse(textwrap.dedent("".join(lines)))
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        raise ValueError("Unsupported original-reader source shape")
    function = tree.body[0]
    args = function.args
    if (function.name != "_read_original" or function.decorator_list or args.posonlyargs
            or [arg.arg for arg in args.args] != ["self", "path"] or args.vararg or args.kwarg
            or args.kwonlyargs or args.defaults):
        raise ValueError("Unsupported original-reader signature")
    native_ast = ast.dump(tree, include_attributes=False)
    temp = "_rust_value_" + uuid4().hex
    prelude = ast.parse(f"{temp} = {bridge_name}(self, path)\nif {temp} is not None:\n    return {temp}\n").body
    offset = int(bool(function.body and isinstance(function.body[0], ast.Expr)
                      and isinstance(function.body[0].value, ast.Constant)
                      and isinstance(function.body[0].value.value, str)))
    function.body[offset:offset] = prelude
    # The rest of the AST must be exactly the original body, including handlers.
    changed = function.body[offset:offset + len(prelude)]
    del function.body[offset:offset + len(prelude)]
    if ast.dump(tree, include_attributes=False) != native_ast:
        raise ValueError("Rust probe changed native fallback statements")
    function.body[offset:offset] = changed
    ast.fix_missing_locations(tree)
    ast.increment_lineno(tree, first - 1)
    local = {}
    exec(compile(tree, archive.__file__, "exec", dont_inherit=True), archive.__dict__, local)
    result = local[function.name]
    result.__qualname__, result.__module__ = original.__qualname__, original.__module__
    result.__annotations__ = dict(original.__annotations__)
    result.__rust_original_reader__ = True
    return result, hashlib.sha256(native_ast.encode()).hexdigest()


@contextmanager
def rust_original_reader(archive_module, module_path, expected_sha256, *, max_depth=64):
    """Temporarily install an optional probe; publish results only after exit.

    Enter before any phase wrappers. This changes one native class method in a
    controlled local worker; concurrent/nested instrumentation is unsupported.
    The extension and native/adapter source bytes must remain unchanged.
    """
    if sys.implementation.name != "cpython" or sys.version_info[:2] != (3, 14):
        raise ValueError("This archive probe is currently qualified only for CPython 3.14")
    if not isinstance(max_depth, int) or isinstance(max_depth, bool) or not 1 <= max_depth <= 64:
        raise ValueError("Rust probe maximum depth must be between one and 64")
    path = Path(module_path).absolute()
    if (path.is_symlink() or not path.is_file() or path.resolve() != path
            or not 0 < path.stat().st_size <= 128 * 1024**2):
        raise ValueError("Rust probe binary must be a pinned regular file")
    path = path.resolve()
    if (not isinstance(expected_sha256, str) or len(expected_sha256) != 64
            or _file_sha(path) != expected_sha256):
        raise ValueError("Rust probe binary hash mismatch")
    native_path, adapter_path = Path(archive_module.__file__).resolve(), Path(__file__).resolve()
    if native_path.parents[3] != adapter_path.parents[1]:
        raise ValueError("Rust adapter and native archive must share the pinned source root")
    extension = _load_extension(path, expected_sha256)
    if (getattr(extension, "PROTOCOL_VERSION", None) != 1
            or not isinstance(getattr(extension, "MAX_FAST_DEPTH", None), int)
            or extension.MAX_FAST_DEPTH < max_depth):
        raise ValueError("Unsupported Rust archive probe protocol or depth contract")
    runtime = _runtime(archive_module)
    stats = dict(closed=False, calls=0, fast_reads=0, native_fallbacks=0, fallback_reasons={},
                 binary_path=str(path), binary_sha256=expected_sha256, runtime=runtime, max_depth=max_depth,
                 native_source_sha256=_file_sha(native_path), adapter_source_sha256=_file_sha(adapter_path),
                 protocol_version=1)
    supported_source = stats["native_source_sha256"] in SUPPORTED_NATIVE_SOURCES
    stats["qualified_native_source"] = supported_source
    bridge_name = "__archive_probe_bridge_" + uuid4().hex
    original = archive_module.ArchiveStore._read_original

    def fallback(reason):
        stats["native_fallbacks"] += 1
        reasons = stats["fallback_reasons"]
        reasons[reason] = reasons.get(reason, 0) + 1
        return None

    def bridge(reader, original_path):
        stats["calls"] += 1
        if not supported_source:
            return fallback("unsupported_source")
        if runtime["limits"]["SCHEMA"] != 1:
            return fallback("unsupported_runtime")
        if _headroom() < MIN_HEADROOM:
            return fallback("low_headroom")
        if _runtime(archive_module) != runtime:
            return fallback("runtime_changed")
        try:
            raw = extension.read_original(str(original_path), max_page_bytes=archive_module.MAX_PAGE_BYTES,
                max_event_bytes=archive_module.MAX_EVENT_BYTES, max_page_events=archive_module.MAX_PAGE_EVENTS,
                max_depth=max_depth)
            if raw is None:
                return fallback("unsupported")
            if (type(raw) is not bytes or len(raw) > archive_module.MAX_PAGE_BYTES + 65536
                    or hashlib.sha256(raw).hexdigest() != Path(original_path).name.removesuffix(".json.gz")):
                return fallback("invalid_return")
            value = json.loads(raw)
            if not isinstance(value, dict):
                return fallback("invalid_return")
        except Exception:
            # Native validation supplies authoritative errors, never extension
            # messages or potentially private payload fragments.
            return fallback("extension_error")
        stats["fast_reads"] += 1
        return value

    replacement, native_ast_sha = _trampoline(original, archive_module, bridge_name)
    stats.update(native_ast_sha256=native_ast_sha,
                 native_code_sha256=hashlib.sha256(marshal.dumps(original.__code__)).hexdigest(),
                 trampoline_code_sha256=hashlib.sha256(marshal.dumps(replacement.__code__)).hexdigest())
    if bridge_name in archive_module.__dict__:
        raise ValueError("Rust probe bridge global collision")
    archive_module.__dict__[bridge_name] = bridge
    archive_module.ArchiveStore._read_original = replacement
    try:
        yield stats
    finally:
        current = archive_module.ArchiveStore._read_original
        archive_module.ArchiveStore._read_original = original
        archive_module.__dict__.pop(bridge_name, None)
        stats["closed"] = True
        if current is not replacement:
            raise ValueError("Rust probe native method was changed during its scope")
        if (_file_sha(path) != expected_sha256 or _file_sha(native_path) != stats["native_source_sha256"]
                or _file_sha(adapter_path) != stats["adapter_source_sha256"] or _runtime(archive_module) != runtime):
            raise ValueError("Rust probe binary, sources or runtime changed during its scope")
