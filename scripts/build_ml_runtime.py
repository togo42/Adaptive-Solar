#!/usr/bin/env python3
"""Create local, deterministic dependency-release assets from explicit inputs.

No downloads, compiler, installation, uploads or productive HA/host changes.
The installation backend remains stdlib-only and copies the fixed Musl wheel.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import sys
import tarfile
import zipfile

REPOSITORY = Path(__file__).resolve().parents[1]
MATERIALS = REPOSITORY / "tools/ml_runtime"
ARTIFACTS = REPOSITORY / "artifacts"
RECORDS_SHA256 = "15b0251c489a771d67999ce35e2378012cc8b8e4b917a6ad25427e8f9aa845ab"
SOURCE_SHA256 = "629cada3e33e2b9bf376cdc7614a47a4140b8aedc1d836579e359736fbd82977"
TAG = "v0.2.23-runtime.1"
GCC_NAME = "gcc-15.2.0.tar.xz"
PATCH_NAME = "gcc-15.2.0-r5-alpine-sources.tar.gz"
ORIGINAL_NAME = "scikit_learn-1.9.1-original-source.tar.gz"
LICENSE_NAMES = ("COPYING", "COPYING3", "COPYING.LIB", "COPYING3.LIB", "COPYING.RUNTIME")


def load_backend():
    spec = importlib.util.spec_from_file_location("ml_delivery_backend", MATERIALS / "backend.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def json_bytes(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verified(backend, path: Path, expected: str, limit: int) -> bytes:
    data = backend.read_regular(path, limit)
    if sha256(data) != expected:
        raise backend.DeliveryError(f"Input SHA256 mismatch: {path.name}")
    return data


def source_material(backend, directory: Path) -> tuple[bytes, bytes, dict[str, bytes]]:
    records_data = verified(backend, MATERIALS / "source-records.json", RECORDS_SHA256, 128 * 1024)
    records = json.loads(records_data)
    recipe = verified(backend, directory / "APKBUILD", records["recipe_sha256"], 128 * 1024)
    checksum_block = re.search(rb'^sha512sums="\n(.*?)\n"', recipe, re.MULTILINE | re.DOTALL)
    if checksum_block is None:
        raise backend.DeliveryError("Missing APKBUILD SHA512 source inventory")
    checksum_rows = [line.split() for line in checksum_block[1].splitlines()]
    recipe_hashes = {name.decode(): checksum.decode() for checksum, name in checksum_rows}
    if len(recipe_hashes) != 45 or recipe_hashes != {
            row["filename"]: row["sha512"] for row in records["files"]}:
        raise backend.DeliveryError("APKBUILD/source-records inventory mismatch")
    content = {"APKBUILD": recipe, "source-records.json": records_data}
    gcc = None
    for row in records["files"]:
        name = row["filename"]
        backend._relative(name)
        data = verified(backend, directory / name, row["sha256"], 128 * 1024 * 1024)
        if len(data) != row["size"] or hashlib.sha512(data).hexdigest() != row["sha512"]:
            raise backend.DeliveryError("Source size or APKBUILD SHA512 mismatch")
        if name == GCC_NAME:
            gcc = data
        else:
            content[name] = data
    if gcc is None:
        raise backend.DeliveryError("Missing full GCC source")
    licenses = {}
    with tarfile.open(fileobj=io.BytesIO(gcc), mode="r:xz") as archive:
        for row in archive:
            prefix = "gcc-15.2.0/"
            if row.name not in {prefix + name for name in LICENSE_NAMES}:
                continue
            name = row.name.removeprefix(prefix)
            if name in licenses or not row.isfile() or not 0 < row.size <= 128 * 1024:
                raise backend.DeliveryError("Ambiguous or oversized GCC license text")
            licenses[name] = archive.extractfile(row).read()
    if set(licenses) != set(LICENSE_NAMES):
        raise backend.DeliveryError("Incomplete GCC license texts")
    content["README.txt"] = (
        f"GCC 15.2.0-r5 Alpine source materials for {TAG}.\n"
        "All 44 patches and APKBUILD are unchanged from the recorded aports commit.\n"
        f"Obtain the adjacent complete {GCC_NAME}; verify SHA256SUMS and source-records.json.\n"
        "The source-records SHA512 values are also checked against APKBUILD.\n"
        "For an independent source build use Alpine's abuild toolchain in a disposable\n"
        "Alpine x86_64 build environment: put APKBUILD and all patches in main/gcc,\n"
        "put the GCC tarball in abuild's source cache, install the recipe's declared\n"
        "build dependencies, and run abuild -r. See https://wiki.alpinelinux.org/wiki/Abuild\n"
        "and https://gcc.gnu.org/install/ for the original build instructions.\n"
        "The pinned HA builder already contains libgcc/libgomp/libstdc++ 15.2.0-r5;\n"
        "the wheel build uses those existing libraries, it does not rebuild GCC.\n"
        "The complete source and recipe are provided, not a byte-reproducible GCC claim.\n"
    ).encode()
    return gcc, backend.sdist_bytes(content, "gcc-15.2.0-r5-alpine-sources"), licenses


def release_content(backend, wheel: Path, sklearn_source: Path, gcc_sources: Path) -> dict[str, bytes]:
    name, expected, tags = backend.WHEELS["musl"]
    wheel_bytes = verified(backend, wheel, expected, backend.MAX_WHEEL)
    metadata = backend.metadata_from_bytes(wheel_bytes, expected, tags)
    source = verified(backend, sklearn_source, SOURCE_SHA256, 32 * 1024 * 1024)
    gcc, patches, licenses = source_material(backend, gcc_sources)
    provenance = json.loads(backend.read_regular(MATERIALS / "provenance.json", 128 * 1024))
    if (provenance["dependency_tag"] != TAG or provenance["scikit_learn"]["wheel_sha256"] != expected
            or provenance["scikit_learn"]["source_sha256"] != SOURCE_SHA256
            or provenance["source_records_sha256"] != RECORDS_SHA256):
        raise backend.DeliveryError("Provenance/material pins disagree")
    with zipfile.ZipFile(io.BytesIO(wheel_bytes)) as archive:
        for row in provenance["libraries"]:
            if sha256(archive.read(row["wheel_path"])) != row["wheel_sha256"]:
                raise backend.DeliveryError("Bundled GCC library provenance mismatch")
    provenance["source_asset_sha256"] = {
        GCC_NAME: sha256(gcc), PATCH_NAME: sha256(patches), ORIGINAL_NAME: sha256(source)}
    provenance["source_asset_base_url"] = (
        f"https://github.com/togo42/Adaptive-Solar/releases/download/{TAG}/")
    provenance_data = json_bytes(provenance)
    notice = backend.read_regular(MATERIALS / "NOTICE.txt", 128 * 1024)
    content = {
        "backend.py": backend.read_regular(MATERIALS / "backend.py", 128 * 1024),
        "pyproject.toml": backend.PYPROJECT,
        "PKG-INFO": metadata["METADATA"],
        "COPYING": metadata["licenses/COPYING"],
        "COPYING3": licenses["COPYING3"],
        "README.txt": notice,
        "NOTICE.txt": notice,
        "provenance.json": provenance_data,
        "source-records.json": backend.read_regular(MATERIALS / "source-records.json", 128 * 1024),
        "wheels/" + name: wheel_bytes,
        **{"licenses/" + name: data for name, data in licenses.items()},
    }
    content["bundle_manifest.json"] = json_bytes({
        "schema": 1, "dependency_tag": TAG,
        "files": {name: sha256(data) for name, data in sorted(content.items())}})
    return {
        backend.SDIST_NAME: backend.sdist_bytes(content),
        GCC_NAME: gcc,
        PATCH_NAME: patches,
        ORIGINAL_NAME: source,
        "provenance.json": provenance_data,
    }


def validate_output(backend, output: Path) -> Path:
    output = output.absolute()
    backend._no_symlinks(output)
    if output.exists() or output.parent != ARTIFACTS.absolute() or not ARTIFACTS.is_dir():
        raise backend.DeliveryError("Output must be a fresh direct child of this checkout's artifacts/")
    return output


def build(wheel: Path, sklearn_source: Path, gcc_sources: Path, output: Path) -> dict:
    backend = load_backend()
    output = validate_output(backend, output)
    # All pins, archive structure, metadata, sources and licenses are checked before mkdir.
    content = release_content(backend, wheel, sklearn_source, gcc_sources)
    sums = "".join(f"{sha256(data)}  {name}\n" for name, data in sorted(content.items())).encode()
    content["SHA256SUMS"] = sums
    output.mkdir(mode=0o700)
    for name, data in sorted(content.items()):
        with (output / name).open("xb") as stream:
            stream.write(data)
    return {"dependency_tag": TAG, "output": str(output),
            "assets": {name: {"sha256": sha256(data), "size": len(data)}
                       for name, data in sorted(content.items())}, "uploaded": False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", required=True, type=Path, help="Already verified pinned Musl wheel")
    parser.add_argument("--sklearn-source", required=True, type=Path, help="Original PyPI 1.9.1 sdist")
    parser.add_argument("--gcc-sources", required=True, type=Path, help="Full GCC source, APKBUILD and all 44 patches")
    parser.add_argument("--output", required=True, type=Path, help="Fresh direct artifacts/ subdirectory")
    args = parser.parse_args(argv)
    try:
        report = build(args.wheel, args.sklearn_source, args.gcc_sources, args.output)
    except (ValueError, OSError, KeyError, tarfile.TarError) as exc:
        parser.exit(2, f"Delivery build refused: {exc}\n")
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
