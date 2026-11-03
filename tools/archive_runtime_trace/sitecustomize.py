"""Chain the original native hook, then opt into independent diagnostics."""

import importlib.machinery as _asrt_machinery
import importlib.util as _asrt_util
import os as _asrt_os
import sys as _asrt_sys

# Native errors deliberately remain outside our diagnostic exception handler.
_asrt_directory = _asrt_os.path.realpath(_asrt_os.path.dirname(__file__))
_asrt_paths = [p for p in _asrt_sys.path if _asrt_os.path.realpath(p) != _asrt_directory]
_asrt_spec = _asrt_machinery.PathFinder.find_spec("sitecustomize", _asrt_paths)
if _asrt_spec is not None:
    _asrt_native = _asrt_util.module_from_spec(_asrt_spec)
    _asrt_sys.modules["sitecustomize"] = _asrt_native
    _asrt_spec.loader.exec_module(_asrt_native)

_asrt_manifest = _asrt_os.environ.get("ADAPTIVE_SOLAR_RUNTIME_TRACE")
if _asrt_manifest:
    # Only our own diagnostics fail open; the native hook already completed.
    try:
        from scripts.archive_runtime_trace import bootstrap

        bootstrap(_asrt_manifest, _asrt_os.environ.get("ADAPTIVE_SOLAR_RUNTIME_TRACE_SHA256"))
    except Exception:
        _asrt_os.write(2, b"Archive runtime telemetry bootstrap failed; native execution continues.\n")
