"""Stdlib-only PEP 517 delivery of one unchanged, authenticated binary wheel.

SPDX-License-Identifier: GPL-3.0-only
No compiler, pip, network, sklearn import or import-path changes. The only
subprocess is the actual ELF interpreter's musl loader, with a five-second limit.
"""
from __future__ import annotations

from email.parser import BytesParser
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import platform
import re
import stat
import struct
import subprocess
import sys
import sysconfig
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parent
DIST_INFO = "scikit_learn-1.9.1.dist-info"
SDIST_NAME = "scikit_learn-1.9.1.tar.gz"
SDIST_ROOT = "scikit_learn-1.9.1"
WHEELS = {
    "musl": (
        "scikit_learn-1.9.1-cp314-cp314-musllinux_1_2_x86_64.whl",
        "7996d012c4aa741cc6386bbc107dec42e53f61ac39c4030362085f20df9293cf",
        {"cp314-cp314-musllinux_1_2_x86_64"},
    ),
}
MAX_WHEEL = 32 * 1024 * 1024
MAX_PAYLOAD = 64 * 1024 * 1024
MAX_METADATA = 8 * 1024 * 1024
PYPROJECT = b'''[build-system]
requires = []
build-backend = "backend"
backend-path = ["."]
'''


class DeliveryError(ValueError):
    """The bundle or interpreter does not meet the declared delivery contract."""


def _no_symlinks(path: Path) -> None:
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise DeliveryError("Symlink in delivery path")


def read_regular(path: Path, limit: int) -> bytes:
    """Read bounded regular files only; all validation precedes output creation."""
    _no_symlinks(path)
    if not path.is_file() or path.stat().st_size > limit:
        raise DeliveryError("Missing regular file or delivery size limit exceeded")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise DeliveryError("Delivery size limit exceeded")
    return data


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _elf_loader(executable: str) -> str | None:
    """Read PT_INTERP from the running executable, not a cross-target setting."""
    try:
        with Path(executable).open("rb") as stream:
            header = stream.read(64)
            if len(header) != 64 or header[:6] != b"\x7fELF\x02\x01":
                return None
            if struct.unpack_from("<H", header, 18)[0] != 62:  # EM_X86_64
                return None
            offset = struct.unpack_from("<Q", header, 32)[0]
            size, count = struct.unpack_from("<HH", header, 54)
            if size != 56 or not 0 < count <= 128 or offset > 1024 * 1024:
                return None
            loaders = []
            for index in range(count):
                stream.seek(offset + index * size)
                row = stream.read(size)
                if len(row) != size:
                    return None
                if struct.unpack_from("<I", row)[0] == 3:  # PT_INTERP
                    start = struct.unpack_from("<Q", row, 8)[0]
                    length = struct.unpack_from("<Q", row, 32)[0]
                    if start > 1024 * 1024 or not 1 < length <= 256:
                        return None
                    stream.seek(start)
                    value = stream.read(length)
                    if not value.endswith(b"\0") or b"\0" in value[:-1]:
                        return None
                    loaders.append(value[:-1].decode("ascii"))
            return loaders[0] if len(loaders) == 1 else None
    except (OSError, UnicodeError, struct.error):
        return None


def runtime_platform() -> dict:
    """Inspect the actual build interpreter, never a requested cross-target."""
    result = {
        "implementation": sys.implementation.name,
        "python": tuple(sys.version_info[:2]),
        "system": sys.platform,
        "machine": platform.machine().lower(),
        "bits": struct.calcsize("P") * 8,
        "soabi": sysconfig.get_config_var("SOABI"),
        "free_threaded": bool(sysconfig.get_config_var("Py_GIL_DISABLED")),
        "loader": _elf_loader(sys.executable),
        "libc_version": None,
    }
    if (result["system"] == "linux" and result["loader"] == "/lib/ld-musl-x86_64.so.1"
            and result["soabi"] == "cpython-314-x86_64-linux-musl"):
        try:
            probe = subprocess.run([result["loader"]], capture_output=True, text=True,
                                   timeout=5, check=False)
            text = probe.stdout + probe.stderr
            match = re.search(r"musl libc .*?\nVersion (\d+)\.(\d+)\.(\d+)\n", text, re.DOTALL)
            if len(text) <= 16384 and match:
                result["libc_version"] = tuple(map(int, match.groups()))
        except (OSError, subprocess.TimeoutExpired, UnicodeError):
            pass  # Unverifiable libc fails closed in platform_key.
    return result


def platform_key(info: dict) -> str:
    if (info.get("implementation") != "cpython" or tuple(info.get("python", ())) != (3, 14)
            or info.get("system") != "linux" or info.get("machine") not in {"x86_64", "amd64"}
            or info.get("bits") != 64 or info.get("free_threaded") is not False):
        raise DeliveryError("Requires normal CPython 3.14, Linux x86_64 (not ARM/PyPy/cp314t)")
    version = info.get("libc_version")
    if (not isinstance(version, (tuple, list)) or len(version) != 3
            or any(type(value) is not int or value < 0 for value in version)):
        raise DeliveryError("Cannot verify the actual interpreter's libc version")
    if (info.get("soabi") == "cpython-314-x86_64-linux-musl"
            and info.get("loader") == "/lib/ld-musl-x86_64.so.1" and tuple(version) >= (1, 2, 0)):
        return "musl"
    raise DeliveryError("Requires musl >=1.2, normal cp314; glibc uses upstream PyPI")


def _relative(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if (not name or "\\" in name or any(ord(char) < 32 for char in name)
            or path.is_absolute() or ".." in path.parts or ":" in name
            or name not in {str(path), str(path) + "/"} or not path.parts
            or len(name.encode("utf-8")) > 1024 or len(path.parts) > 32
            or any(len(part.encode("utf-8")) > 255 for part in path.parts)):
        raise DeliveryError("Unsafe or noncanonical archive path")
    return path


def _check_tree(files: set[str], directories: set[str]) -> None:
    if files & directories or any(str(parent) in files for name in files | directories
                                  for parent in PurePosixPath(name).parents if str(parent) != "."):
        raise DeliveryError("Archive file/directory collision")


def metadata_from_bytes(data: bytes, expected_hash: str, tags: set[str]) -> dict[str, bytes]:
    """Authenticate before ZIP parsing; reject ambiguities before any extraction."""
    if len(data) > MAX_WHEEL or hashlib.sha256(data).hexdigest() != expected_hash:
        raise DeliveryError("Pinned wheel SHA256 mismatch or oversized wheel")
    metadata: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > 50000 or sum(row.file_size for row in members) > 512 * 1024 * 1024:
                raise DeliveryError("Wheel exceeds delivery limits")
            seen, files, directories = set(), set(), set()
            metadata_size = 0
            for row in members:
                relative = _relative(row.filename)
                name = str(relative)
                mode = stat.S_IFMT(row.external_attr >> 16)
                if (name in seen or row.orig_filename != row.filename or row.flag_bits & 1
                        or mode not in {0, stat.S_IFREG, stat.S_IFDIR}
                        or mode == stat.S_IFDIR and not row.is_dir()
                        or mode == stat.S_IFREG and row.is_dir()):
                    raise DeliveryError("Duplicate, special, encrypted or ambiguous ZIP member")
                seen.add(name)
                (directories if row.is_dir() else files).add(name)
                if any(part.endswith(".dist-info") for part in relative.parts):
                    if relative.parts[0] != DIST_INFO or any(
                            part.endswith(".dist-info") for part in relative.parts[1:]):
                        raise DeliveryError("Ambiguous distribution metadata")
                if relative.parts[0] != DIST_INFO or row.is_dir():
                    # Validate local headers even for payloads we never extract.
                    # ZipFile.open checks local/central name equality and overlap.
                    with archive.open(row):
                        pass
                    continue
                metadata_size += row.file_size
                if len(relative.parts) < 2 or row.file_size > 2 * 1024 * 1024 or metadata_size > MAX_METADATA:
                    raise DeliveryError("Oversized or invalid distribution metadata")
                metadata[str(PurePosixPath(*relative.parts[1:]))] = archive.read(row)
            _check_tree(files, directories)
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError, OSError) as exc:
        raise DeliveryError("Invalid wheel ZIP") from exc
    if not {"METADATA", "WHEEL", "RECORD"} <= metadata.keys():
        raise DeliveryError("Incomplete distribution metadata")
    metadata_entries = set(metadata) | {str(parent) for name in metadata
                                       for parent in PurePosixPath(name).parents if str(parent) != "."}
    if len(metadata_entries) > 256:
        raise DeliveryError("Too many distribution metadata entries")
    package = BytesParser().parsebytes(metadata["METADATA"])
    wheel = BytesParser().parsebytes(metadata["WHEEL"])
    if package.get_all("Name") != ["scikit-learn"] or package.get_all("Version") != ["1.9.1"]:
        raise DeliveryError("Wheel distribution identity mismatch")
    if (set(wheel.get_all("Tag", [])) != tags or wheel.get_all("Root-Is-Purelib") != ["false"]
            or wheel.get_all("Wheel-Version") != ["1.0"]):
        raise DeliveryError("Wheel ABI tags or binary metadata mismatch")
    return metadata


def wheel_metadata(path: Path, expected_hash: str, tags: set[str]) -> dict[str, bytes]:
    return metadata_from_bytes(read_regular(path, MAX_WHEEL), expected_hash, tags)


def selected_wheel() -> tuple[str, bytes, dict[str, bytes]]:
    name, expected_hash, tags = WHEELS[platform_key(runtime_platform())]
    data = read_regular(ROOT / "wheels" / name, MAX_WHEEL)
    return name, data, metadata_from_bytes(data, expected_hash, tags)


def _output_directory(value: str) -> Path:
    path = Path(value).absolute()
    _no_symlinks(path)
    if not path.is_dir():
        raise DeliveryError("Output must be an existing directory without symlink parents")
    return path


def get_requires_for_build_wheel(config_settings=None) -> list[str]:
    return []


def get_requires_for_build_sdist(config_settings=None) -> list[str]:
    return []


def prepare_metadata_for_build_wheel(metadata_directory, config_settings=None) -> str:
    _, _, metadata = selected_wheel()
    target = _output_directory(metadata_directory) / DIST_INFO
    target.mkdir()  # Never merge metadata with a previous attempt.
    for name, content in sorted(metadata.items()):
        output = target.joinpath(*_relative(name).parts)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as stream:
            stream.write(content)
    return DIST_INFO


def _check_prepared(value: str, metadata: dict[str, bytes]) -> None:
    # PEP 517 passes the dist-info directory itself, not its parent.
    prepared = _output_directory(value)
    if prepared.name != DIST_INFO:
        raise DeliveryError("Expected the previously prepared dist-info directory")
    actual = {}
    total = 0
    for index, item in enumerate(prepared.rglob("*")):
        if index >= 256:
            raise DeliveryError("Too many previously prepared metadata entries")
        _no_symlinks(item)
        if item.is_dir():
            continue
        data = read_regular(item, 2 * 1024 * 1024)
        total += len(data)
        if total > MAX_METADATA:
            raise DeliveryError("Oversized previously prepared metadata")
        actual[item.relative_to(prepared).as_posix()] = data
    if actual != metadata:
        raise DeliveryError("Previously prepared metadata changed")


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None) -> str:
    name, data, metadata = selected_wheel()
    if metadata_directory is not None:
        _check_prepared(metadata_directory, metadata)
    output = _output_directory(wheel_directory) / name
    with output.open("xb") as stream:
        stream.write(data)  # Exactly the authenticated bytes; never repack the wheel.
    return name


def sdist_bytes(content: dict[str, bytes], root: str = SDIST_ROOT) -> bytes:
    """PEP 517 PAX tar.gz, normalized ownership/mode/order/mtime/gzip header."""
    _relative(root)
    for name in content:
        _relative(name)
    _check_tree(set(content), set())
    result = io.BytesIO()
    with gzip.GzipFile(fileobj=result, mode="wb", filename="", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
            directory = tarfile.TarInfo(root + "/")
            directory.type, directory.mode = tarfile.DIRTYPE, 0o755
            archive.addfile(directory)
            for name, data in sorted(content.items()):
                info = tarfile.TarInfo(root + "/" + name)
                info.size, info.mode, info.mtime = len(data), 0o644, 0
                archive.addfile(info, io.BytesIO(data))
    return result.getvalue()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DeliveryError("Duplicate bundle inventory key")
        result[key] = value
    return result


def build_sdist(sdist_directory, config_settings=None) -> str:
    """Rebuild the authenticated delivery container on any maintainer platform."""
    manifest_data = read_regular(ROOT / "bundle_manifest.json", 128 * 1024)
    manifest = json.loads(manifest_data, object_pairs_hook=_unique_object)
    files = manifest.get("files")
    name, expected_hash, tags = WHEELS["musl"]
    required = {"backend.py", "pyproject.toml", "PKG-INFO", "wheels/" + name}
    if (manifest.get("schema") != 1 or not isinstance(files, dict) or len(files) > 256
            or not required <= files.keys() or "bundle_manifest.json" in files):
        raise DeliveryError("Invalid, incomplete or recursive bundle inventory")
    if {filename for filename in files if filename.endswith(".whl")} != {"wheels/" + name}:
        raise DeliveryError("Only the pinned Musl wheel belongs in this delivery bundle")
    _check_tree(set(files) | {"bundle_manifest.json"}, set())
    content = {"bundle_manifest.json": manifest_data}
    total = len(manifest_data)
    for filename, expected in files.items():
        path = ROOT.joinpath(*_relative(filename).parts)
        data = read_regular(path, MAX_PAYLOAD - total)
        if hashlib.sha256(data).hexdigest() != expected:
            raise DeliveryError("Source-delivery payload SHA256 mismatch")
        total += len(data)
        content[filename] = data
    metadata = metadata_from_bytes(content["wheels/" + name], expected_hash, tags)
    if content["pyproject.toml"] != PYPROJECT or content["PKG-INFO"] != metadata["METADATA"]:
        raise DeliveryError("Source-delivery build configuration or metadata changed")
    data = sdist_bytes(content)
    destination = _output_directory(sdist_directory) / SDIST_NAME
    with destination.open("xb") as stream:
        stream.write(data)
    return SDIST_NAME
