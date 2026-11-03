#!/usr/bin/env python3
"""Prepare explicit native activation pins; never install or activate them."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import native_quality_backend as backend  # noqa: E402


def _sha(path):
    result = hashlib.sha256()
    with path.open("rb") as handle:
        while part := handle.read(1024 * 1024):
            result.update(part)
    return result.hexdigest()


def build_manifest(source_root, release_root, binary, runtime):
    """Bind reviewed source bytes to a named release and exact host runtime."""
    source = Path(source_root).absolute()
    release = str(release_root)
    if (source.is_symlink() or source.resolve() != source or not source.is_dir()
            or not PurePosixPath(release).is_absolute() or str(PurePosixPath(release)) != release
            or ".." in PurePosixPath(release).parts):
        raise ValueError("Canonical source and absolute release roots are required")
    expected_runtime = {"implementation", "version", "soabi", "gil_disabled", "python_binary_sha256", "dependencies"}
    if (not isinstance(runtime, dict) or set(runtime) != expected_runtime
            or runtime["implementation"] != "cpython" or not isinstance(runtime["version"], str)
            or not runtime["version"].startswith("3.14.") or not isinstance(runtime["soabi"], str)
            or not runtime["soabi"].startswith("cpython-314-")
            or type(runtime["gil_disabled"]) is not int or runtime["gil_disabled"] != 0
            or not isinstance(runtime["python_binary_sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", runtime["python_binary_sha256"]) is None
            or not isinstance(runtime["dependencies"], dict)
            or set(runtime["dependencies"]) != set(backend.DEPENDENCIES)
            or any(not isinstance(value, str) or not value for value in runtime["dependencies"].values())):
        raise ValueError("Exact qualified interpreter and numerical dependency pins are required")
    binary = Path(binary).absolute()
    if (binary.is_symlink() or binary.resolve() != binary or not binary.is_file()
            or not 0 < binary.stat().st_size <= 128 * 1024**2):
        raise ValueError("A bounded canonical native binary is required")
    sources = {}
    for name in sorted(backend.SOURCE_FILES):
        path = backend._member(source, name)
        if path.stat().st_size > 128 * 1024**2:
            raise ValueError("Native source exceeds byte budget")
        sources[name] = _sha(path)
    if (sources["custom_components/adaptive_solar/core/archive.py"] not in backend.SUPPORTED_ARCHIVE_SOURCES
            or sources["custom_components/adaptive_solar/core/actual_quality.py"] not in backend.SUPPORTED_FACTORY_SOURCES):
        raise ValueError("Native reader or configuration factory is not qualified")
    return {"schema": backend.SCHEMA, "protocol_version": 2, "source_root": release, "sources": sources,
            "binary": {"path": "native/lib_archive_probe.so", "sha256": _sha(binary)},
            "runtime": runtime}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--release-root", required=True, help="Canonical final host release path")
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--runtime-json", type=Path, required=True, help="Exact six-field host runtime evidence")
    parser.add_argument("--output", type=Path, required=True, help="New private data/ or artifacts/ manifest file")
    args = parser.parse_args(argv)
    output = args.output.absolute()
    allowed = ((ROOT / "data").resolve(), (ROOT / "artifacts").resolve())
    if (output.exists() or output.is_symlink()
            or not any(output.resolve().is_relative_to(parent) for parent in allowed)
            or output.resolve() in {args.binary.resolve(), args.runtime_json.resolve()}
            or output.resolve().is_relative_to(args.source_root.resolve() / "custom_components")
            or output.resolve().is_relative_to(args.source_root.resolve() / "scripts")):
        parser.error("Output must be new private evidence outside protected sources and inputs")
    try:
        if (args.runtime_json.is_symlink() or not args.runtime_json.is_file()
                or args.runtime_json.stat().st_size > 1024**2):
            raise ValueError("Invalid host runtime evidence file")
        runtime = json.loads(args.runtime_json.read_bytes(), object_pairs_hook=backend._unique_object)
        manifest = build_manifest(args.source_root, args.release_root, args.binary, runtime)
        data = (json.dumps(manifest, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
        output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with output.open("xb") as handle:
            handle.write(data)
        output.chmod(0o600)
        print(json.dumps({"status": "prepared_not_activated", "manifest_sha256": hashlib.sha256(data).hexdigest(),
                          "source_files": len(manifest["sources"]), "binary_sha256": manifest["binary"]["sha256"]}))
        return 0
    except (OSError, ValueError, TypeError, KeyError):
        print("Native activation manifest preparation failed.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
