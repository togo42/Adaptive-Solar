"""Offline PEP 517 delivery contract; synthetic non-executable wheel/source fixtures."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import socket
import stat
import struct
import subprocess
import tarfile
from types import SimpleNamespace
import warnings
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


backend = load("runtime_backend_under_test", ROOT / "tools/ml_runtime/backend.py")
builder = load("runtime_bundle_builder_under_test", ROOT / "scripts/build_ml_runtime.py")
TAG = "cp314-cp314-musllinux_1_2_x86_64"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def supported():
    return {"implementation": "cpython", "python": (3, 14), "system": "linux",
            "machine": "x86_64", "bits": 64, "soabi": "cpython-314-x86_64-linux-musl",
            "free_threaded": False, "loader": "/lib/ld-musl-x86_64.so.1", "libc_version": (1, 2, 5)}


def wheel_bytes(extra=(), metadata=None):
    rows = {
        backend.DIST_INFO + "/METADATA": b"Metadata-Version: 2.4\nName: scikit-learn\nVersion: 1.9.1\n",
        backend.DIST_INFO + "/WHEEL": (
            f"Wheel-Version: 1.0\nRoot-Is-Purelib: false\nTag: {TAG}\n").encode(),
        backend.DIST_INFO + "/RECORD": b"synthetic RECORD fixture\n",
        backend.DIST_INFO + "/licenses/COPYING": b"synthetic BSD license fixture\n",
        backend.DIST_INFO + "/sboms/auditwheel.cdx.json": b"{}\n",
        "sklearn/__init__.py": b"raise AssertionError('must never import wheel payload')\n",
        "scikit_learn.libs/libgomp-fixture.so.1": b"not an executable library",
    }
    rows.update(metadata or {})
    stream = io.BytesIO()
    with warnings.catch_warnings(), zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        warnings.filterwarnings("ignore", message="Duplicate name:", category=UserWarning)
        for name, data in [*rows.items(), *extra]:
            archive.writestr(name, data)
    return stream.getvalue()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Unit tests must not access the network")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


@pytest.fixture
def bundle(monkeypatch, tmp_path):
    root = tmp_path / "bundle"
    (root / "wheels").mkdir(parents=True)
    data = wheel_bytes()
    name = backend.WHEELS["musl"][0]
    (root / "wheels" / name).write_bytes(data)
    monkeypatch.setattr(backend, "WHEELS", {"musl": (name, sha(data), {TAG})})
    monkeypatch.setattr(backend, "ROOT", root)
    monkeypatch.setattr(backend, "runtime_platform", supported)
    return root, name, data


def assert_empty(path):
    assert list(path.iterdir()) == []


@pytest.mark.parametrize("change", [
    {"implementation": "pypy"}, {"python": (3, 13)}, {"python": (3, 15)},
    {"system": "darwin"}, {"machine": "aarch64"}, {"bits": 32},
    {"free_threaded": True}, {"free_threaded": None},
    {"soabi": "cpython-314t-x86_64-linux-musl"},
    {"soabi": "cpython-314-x86_64-linux-gnu", "libc_version": (2, 42, 0)},
    {"loader": "/lib64/ld-linux-x86-64.so.2"}, {"libc_version": None},
    {"libc_version": (1, 1, 24)}, {"libc_version": (True, 2, 5)},
    {"libc_version": (1, 2)}, {"libc_version": (-1, 2, 3)},
])
def test_unsupported_interpreter_has_no_output(bundle, monkeypatch, tmp_path, change):
    monkeypatch.setattr(backend, "runtime_platform", lambda: {**supported(), **change})
    output = tmp_path / "output"
    output.mkdir()
    for hook in (backend.prepare_metadata_for_build_wheel, backend.build_wheel):
        with pytest.raises(backend.DeliveryError):
            hook(str(output), config_settings={"platform": TAG})
        assert_empty(output)


@pytest.mark.parametrize("version", [(1, 2, 0), (1, 2, 5), (1, 3, 0)])
def test_musl_minimum(version):
    assert backend.platform_key({**supported(), "libc_version": version}) == "musl"


def test_stdlib_build_system_needs_no_build_dependencies():
    import tomllib
    assert tomllib.loads(backend.PYPROJECT.decode()) == {
        "build-system": {"requires": [], "build-backend": "backend", "backend-path": ["."]}}
    assert backend.get_requires_for_build_wheel() == []
    assert backend.get_requires_for_build_sdist() == []


def test_copy_wheel_and_prepared_metadata_are_byte_identical(bundle, tmp_path, monkeypatch):
    root, name, data = bundle
    metadata = tmp_path / "metadata"
    output = tmp_path / "output"
    metadata.mkdir()
    output.mkdir()
    def forbidden(*args, **kwargs):
        pytest.fail("Wheel delivery must not invoke pip, a compiler or any subprocess")
    monkeypatch.setattr(backend.subprocess, "run", forbidden)
    dist = backend.prepare_metadata_for_build_wheel(str(metadata))
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        expected = {p.removeprefix(dist + "/"): archive.read(p)
                    for p in archive.namelist() if p.startswith(dist + "/")}
    actual = {p.relative_to(metadata / dist).as_posix(): p.read_bytes()
              for p in (metadata / dist).rglob("*") if p.is_file()}
    assert actual == expected
    assert backend.build_wheel(str(output), metadata_directory=str(metadata / dist)) == name
    assert (output / name).read_bytes() == data == (root / "wheels" / name).read_bytes()
    with pytest.raises(FileExistsError):
        backend.build_wheel(str(output))
    assert (output / name).read_bytes() == data


@pytest.mark.parametrize("mutation", ["edit", "missing", "extra", "symlink", "oversized", "parent"])
def test_prepared_metadata_mutation_refuses_before_wheel_write(bundle, tmp_path, mutation):
    metadata = tmp_path / "metadata"
    output = tmp_path / "output"
    metadata.mkdir()
    output.mkdir()
    dist = metadata / backend.prepare_metadata_for_build_wheel(str(metadata))
    target = dist / "METADATA"
    if mutation == "edit":
        target.write_bytes(b"changed")
    elif mutation == "missing":
        target.unlink()
    elif mutation == "extra":
        (dist / "unpreserved").write_bytes(b"extra")
    elif mutation == "symlink":
        target.unlink()
        target.symlink_to(dist / "WHEEL")
    elif mutation == "oversized":
        target.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    else:
        dist = metadata
    with pytest.raises(backend.DeliveryError):
        backend.build_wheel(str(output), metadata_directory=str(dist))
    assert_empty(output)


@pytest.mark.parametrize("mutation", ["wrong-hash", "missing", "symlink", "parent-symlink", "oversized"])
def test_untrusted_wheel_refuses_before_metadata_write(bundle, tmp_path, monkeypatch, mutation):
    root, name, data = bundle
    path = root / "wheels" / name
    if mutation == "wrong-hash":
        path.write_bytes(data + b"changed")
    elif mutation == "missing":
        path.unlink()
    elif mutation == "symlink":
        path.unlink()
        original = tmp_path / "wheel-original"
        original.write_bytes(data)
        path.symlink_to(original)
    elif mutation == "parent-symlink":
        path.parent.rename(root / "originals")
        path.parent.symlink_to(root / "originals", target_is_directory=True)
    else:
        monkeypatch.setattr(backend, "MAX_WHEEL", len(data) - 1)
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(backend.DeliveryError):
        backend.prepare_metadata_for_build_wheel(str(out))
    assert_empty(out)


@pytest.mark.parametrize("name", ["../outside", "/absolute", "a/../../b", "a\\b", "a//b",
                                  "a/./b", "C:drive", "./a", "a//"])
def test_unsafe_archive_paths_are_rejected(name):
    data = wheel_bytes(extra=[(name, b"unsafe")])
    with pytest.raises(backend.DeliveryError):
        backend.metadata_from_bytes(data, sha(data), {TAG})


def test_null_filename_is_rejected_without_synthetic_writer_normalization():
    # ZipInfo itself truncates NUL names on writing. Change stored local AND
    # central filenames instead so the test actually exercises hostile bytes.
    data = wheel_bytes(extra=[("nullXentry", b"unsafe")]).replace(b"nullXentry", b"null\0entry")
    with pytest.raises(backend.DeliveryError):
        backend.metadata_from_bytes(data, sha(data), {TAG})


def test_payload_local_and_central_zip_names_must_match():
    data = wheel_bytes(extra=[("payload-name", b"unsafe")])
    # Change only the local name; the central directory still names payload-name.
    data = data.replace(b"payload-name", b"changed-name", 1)
    with pytest.raises(backend.DeliveryError, match="ZIP"):
        backend.metadata_from_bytes(data, sha(data), {TAG})


@pytest.mark.parametrize("extra", [
    [(backend.DIST_INFO + "/METADATA", b"duplicate")],
    [("different-1.dist-info/METADATA", b"ambiguous")],
    [("nested/another.dist-info/METADATA", b"ambiguous")],
    [("parent", b"file"), ("parent/child", b"collision")],
    [("directory/", b""), ("directory", b"collision")],
])
def test_zip_ambiguity_is_rejected_before_any_extraction(extra):
    data = wheel_bytes(extra=extra)
    with pytest.raises(backend.DeliveryError):
        backend.metadata_from_bytes(data, sha(data), {TAG})


@pytest.mark.parametrize("mode", [stat.S_IFLNK, stat.S_IFIFO, stat.S_IFCHR])
def test_zip_special_entries_rejected(mode):
    row = zipfile.ZipInfo("unsafe-entry")
    row.external_attr = (mode | 0o777) << 16
    data = wheel_bytes(extra=[(row, b"target")])
    with pytest.raises(backend.DeliveryError):
        backend.metadata_from_bytes(data, sha(data), {TAG})


@pytest.mark.parametrize("content", [
    b"Name: other\nVersion: 1.9.1\n", b"Name: scikit-learn\nVersion: 9\n",
    b"Name: scikit-learn\nName: other\nVersion: 1.9.1\n",
])
def test_metadata_identity_not_just_directory_name(content):
    data = wheel_bytes(metadata={backend.DIST_INFO + "/METADATA": content})
    with pytest.raises(backend.DeliveryError, match="identity"):
        backend.metadata_from_bytes(data, sha(data), {TAG})


def test_oversized_metadata_and_wrong_tags_are_rejected():
    for content in (b"x" * (2 * 1024 * 1024 + 1), b"Tag: cp314-cp314-manylinux_2_28_x86_64\n"):
        data = wheel_bytes(metadata={backend.DIST_INFO + "/WHEEL": content})
        with pytest.raises(backend.DeliveryError):
            backend.metadata_from_bytes(data, sha(data), {TAG})


def test_metadata_count_and_path_size_abort_before_metadata_directory(bundle, tmp_path, monkeypatch):
    root, name, _ = bundle
    for extra in ([(backend.DIST_INFO + f"/extras/{index}", b"") for index in range(257)],
                  [(backend.DIST_INFO + "/" + "x" * 256, b"oversized path")]):
        data = wheel_bytes(extra=extra)
        (root / "wheels" / name).write_bytes(data)
        monkeypatch.setattr(backend, "WHEELS", {"musl": (name, sha(data), {TAG})})
        with pytest.raises(backend.DeliveryError):
            backend.prepare_metadata_for_build_wheel(str(tmp_path))
        assert not (tmp_path / backend.DIST_INFO).exists()


def test_hash_verified_before_zip_is_opened(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Unauthenticated ZIP must not be parsed")
    monkeypatch.setattr(zipfile, "ZipFile", forbidden)
    with pytest.raises(backend.DeliveryError, match="SHA256"):
        backend.metadata_from_bytes(b"not ZIP", "0" * 64, {TAG})


def test_output_symlink_refused_without_touching_target(bundle, tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(backend.DeliveryError, match="Symlink"):
        backend.prepare_metadata_for_build_wheel(str(link))
    assert_empty(real)


def elf_bytes(loader=b"/lib/ld-musl-x86_64.so.1\0"):
    value = bytearray(512)
    value[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<H", value, 18, 62)
    struct.pack_into("<Q", value, 32, 64)
    struct.pack_into("<HH", value, 54, 56, 1)
    struct.pack_into("<I", value, 64, 3)
    struct.pack_into("<Q", value, 72, 256)
    struct.pack_into("<Q", value, 96, len(loader))
    value[256:256 + len(loader)] = loader
    return value


def test_actual_elf_loader_and_malformed_elf(tmp_path):
    executable = tmp_path / "python"
    executable.write_bytes(elf_bytes())
    assert backend._elf_loader(str(executable)) == "/lib/ld-musl-x86_64.so.1"
    for data in (b"", b"not ELF", elf_bytes(loader=b"missing-null")):
        executable.write_bytes(data)
        assert backend._elf_loader(str(executable)) is None


@pytest.mark.parametrize("result", ["valid", "timeout", "wrong-text", "oversized"])
def test_version_probe_has_fixed_command_and_deadline(monkeypatch, tmp_path, result):
    probe_backend = load("probe_backend", ROOT / "tools/ml_runtime/backend.py")
    executable = tmp_path / "python"
    executable.write_bytes(elf_bytes())
    monkeypatch.setattr(probe_backend.sys, "executable", str(executable))
    monkeypatch.setattr(probe_backend.sys, "platform", "linux")
    monkeypatch.setattr(probe_backend.sysconfig, "get_config_var", lambda key: {
        "SOABI": "cpython-314-x86_64-linux-musl", "Py_GIL_DISABLED": 0}.get(key))
    calls = []
    def probe(argv, **kwargs):
        calls.append((argv, kwargs))
        if result == "timeout":
            raise subprocess.TimeoutExpired(argv, 5)
        text = "musl libc (x86_64)\nVersion 1.2.5\n"
        if result == "wrong-text":
            text = "Version 9.9.9\n"
        elif result == "oversized":
            text += "x" * 16385
        return SimpleNamespace(stdout="", stderr=text)
    monkeypatch.setattr(probe_backend.subprocess, "run", probe)
    info = probe_backend.runtime_platform()
    assert info["libc_version"] == ((1, 2, 5) if result == "valid" else None)
    assert calls == [(["/lib/ld-musl-x86_64.so.1"], {
        "capture_output": True, "text": True, "timeout": 5, "check": False})]


def add_inventory(root, data, name):
    content = {"backend.py": b"# backend fixture\n", "pyproject.toml": backend.PYPROJECT,
               "PKG-INFO": backend.metadata_from_bytes(data, sha(data), {TAG})["METADATA"],
               "wheels/" + name: data, "licenses/COPYING3": b"synthetic license"}
    for filename, value in content.items():
        path = root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    (root / "bundle_manifest.json").write_bytes(builder.json_bytes({
        "schema": 1, "files": {filename: sha(value) for filename, value in content.items()}}))
    return content


def test_sdist_deterministic_pax_root_metadata_licenses_and_rebuild(bundle, tmp_path):
    root, name, data = bundle
    content = add_inventory(root, data, name)
    outputs = [tmp_path / "first", tmp_path / "second"]
    for directory in outputs:
        directory.mkdir()
        assert backend.build_sdist(str(directory)) == backend.SDIST_NAME
    first, second = [(directory / backend.SDIST_NAME).read_bytes() for directory in outputs]
    assert first == second
    assert first[4:8] == b"\0\0\0\0"  # gzip mtime
    assert not first[3] & 8  # no source filename
    with tarfile.open(fileobj=io.BytesIO(first), mode="r:gz") as archive:
        members = archive.getmembers()
        assert members[0].name == backend.SDIST_ROOT and members[0].isdir()
        assert [row.name for row in members[1:]] == sorted(row.name for row in members[1:])
        for row in members:
            assert row.uid == row.gid == row.mtime == 0
            assert row.uname == row.gname == ""
            assert row.mode == (0o755 if row.isdir() else 0o644)
            if row.isfile():
                assert archive.extractfile(row).read() == (root / row.name.split("/", 1)[1]).read_bytes()
        assert archive.extractfile(backend.SDIST_ROOT + "/PKG-INFO").read() == content["PKG-INFO"]
    # PAX must also represent long Unicode paths (not the old GNU tar dialect).
    value = backend.sdist_bytes({"licenses/" + "ä" * 100: b"license"})
    with tarfile.open(fileobj=io.BytesIO(value)) as archive:
        assert "path" in archive.getmembers()[1].pax_headers


@pytest.mark.parametrize("mutation", ["payload", "manifest-symlink", "traversal", "duplicate", "wheel-pin", "extra-wheel"])
def test_sdist_invalid_inventory_has_no_output(bundle, tmp_path, mutation):
    root, name, data = bundle
    add_inventory(root, data, name)
    manifest = root / "bundle_manifest.json"
    if mutation == "payload":
        (root / "PKG-INFO").write_bytes(b"changed")
    elif mutation == "manifest-symlink":
        manifest.rename(root / "real-manifest")
        manifest.symlink_to(root / "real-manifest")
    elif mutation == "traversal":
        value = json.loads(manifest.read_bytes())
        value["files"]["../outside"] = sha(b"x")
        manifest.write_bytes(builder.json_bytes(value))
    elif mutation == "duplicate":
        manifest.write_bytes(b'{"schema":1,"schema":1,"files":{}}')
    elif mutation == "wheel-pin":
        path = root / "wheels" / name
        path.write_bytes(data + b"different wheel")
        value = json.loads(manifest.read_bytes())
        value["files"]["wheels/" + name] = sha(path.read_bytes())
        manifest.write_bytes(builder.json_bytes(value))
    else:
        value = json.loads(manifest.read_bytes())
        value["files"]["wheels/glibc.whl"] = sha(b"not distributed")
        manifest.write_bytes(builder.json_bytes(value))
    output = tmp_path / "output"
    output.mkdir()
    with pytest.raises(backend.DeliveryError):
        backend.build_sdist(str(output))
    assert_empty(output)


@pytest.fixture
def release_inputs(bundle, tmp_path, monkeypatch):
    root, wheel_name, data = bundle
    materials = tmp_path / "materials"
    materials.mkdir()
    for filename in ("backend.py", "NOTICE.txt", "provenance.json"):
        (materials / filename).write_bytes((ROOT / "tools/ml_runtime" / filename).read_bytes())
    sources = tmp_path / "sources"
    sources.mkdir()
    stream = io.BytesIO()
    license_texts = {name: ("synthetic full text " + name).encode() for name in builder.LICENSE_NAMES}
    with tarfile.open(fileobj=stream, mode="w:xz") as archive:
        for name, text in license_texts.items():
            row = tarfile.TarInfo("gcc-15.2.0/" + name)
            row.size = len(text)
            archive.addfile(row, io.BytesIO(text))
    gcc = stream.getvalue()
    records = {"aports_commit": "synthetic", "files": []}
    source_bytes = {builder.GCC_NAME: gcc, **{f"{index:04d}.patch": b"fixture patch" for index in range(44)}}
    for name, value in source_bytes.items():
        (sources / name).write_bytes(value)
        records["files"].append({"filename": name, "size": len(value),
                                 "sha256": sha(value), "sha512": hashlib.sha512(value).hexdigest()})
    recipe = ('sha512sums="\n' + "\n".join(
        f'{row["sha512"]}  {row["filename"]}' for row in records["files"]) + '\n"\n').encode()
    records["recipe_sha256"] = sha(recipe)
    (sources / "APKBUILD").write_bytes(recipe)
    records_data = builder.json_bytes(records)
    (materials / "source-records.json").write_bytes(records_data)
    original = tmp_path / "sklearn-original.tar.gz"
    original.write_bytes(b"synthetic original source")
    provenance = json.loads((materials / "provenance.json").read_bytes())
    provenance["scikit_learn"]["wheel_sha256"] = sha(data)
    provenance["scikit_learn"]["source_sha256"] = sha(original.read_bytes())
    provenance["source_records_sha256"] = sha(records_data)
    provenance["libraries"] = [{"wheel_path": "scikit_learn.libs/libgomp-fixture.so.1",
                                "wheel_sha256": sha(b"not an executable library")}]
    (materials / "provenance.json").write_bytes(builder.json_bytes(provenance))
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setattr(builder, "ARTIFACTS", artifacts)
    monkeypatch.setattr(builder, "MATERIALS", materials)
    monkeypatch.setattr(builder, "SOURCE_SHA256", sha(original.read_bytes()))
    monkeypatch.setattr(builder, "RECORDS_SHA256", sha(records_data))
    monkeypatch.setattr(builder, "load_backend", lambda: backend)
    return SimpleNamespace(wheel=root / "wheels" / wheel_name, original=original, sources=sources,
                           artifacts=artifacts, materials=materials, gcc=gcc, licenses=license_texts)


def test_release_has_all_separate_source_assets_and_checksums(release_inputs):
    f = release_inputs
    outputs = [f.artifacts / "first", f.artifacts / "second"]
    for output in outputs:
        report = builder.build(f.wheel, f.original, f.sources, output)
        assert report["uploaded"] is False
    assert {p.name: p.read_bytes() for p in outputs[0].iterdir()} == {
        p.name: p.read_bytes() for p in outputs[1].iterdir()}
    output = outputs[0]
    for line in (output / "SHA256SUMS").read_text().splitlines():
        expected, name = line.split("  ")
        assert sha((output / name).read_bytes()) == expected
    assert (output / builder.GCC_NAME).read_bytes() == f.gcc
    assert (output / builder.ORIGINAL_NAME).read_bytes() == f.original.read_bytes()
    with tarfile.open(output / builder.PATCH_NAME) as archive:
        names = archive.getnames()
        assert sum(name.endswith(".patch") for name in names) == 44
        assert any(name.endswith("/APKBUILD") for name in names)
        assert not any(name.endswith(".xz") for name in names)
    with tarfile.open(output / backend.SDIST_NAME) as archive:
        prefix = backend.SDIST_ROOT + "/"
        for name, text in f.licenses.items():
            assert archive.extractfile(prefix + "licenses/" + name).read() == text
        assert archive.extractfile(prefix + "wheels/" + f.wheel.name).read() == f.wheel.read_bytes()
        notice = archive.extractfile(prefix + "NOTICE.txt").read().decode()
        for asset in (builder.GCC_NAME, builder.PATCH_NAME, builder.ORIGINAL_NAME):
            assert f"releases/download/{builder.TAG}/{asset}" in notice
        assert not any("manylinux" in name for name in archive.getnames())


@pytest.mark.parametrize("mutation", ["wheel", "original", "patch", "gcc", "recipe", "records", "license"])
def test_release_input_failure_precedes_output_creation(release_inputs, mutation):
    f = release_inputs
    paths = {"wheel": f.wheel, "original": f.original, "patch": f.sources / "0000.patch",
             "gcc": f.sources / builder.GCC_NAME, "recipe": f.sources / "APKBUILD",
             "records": f.materials / "source-records.json", "license": f.sources / builder.GCC_NAME}
    paths[mutation].write_bytes(b"invalid input")
    output = f.artifacts / "refused"
    with pytest.raises(backend.DeliveryError):
        builder.build(f.wheel, f.original, f.sources, output)
    assert not output.exists()


def test_release_output_guard_never_reuses_or_escapes_artifacts(release_inputs, tmp_path):
    f = release_inputs
    existing = f.artifacts / "existing"
    existing.mkdir()
    marker = existing / "untouched"
    marker.write_bytes(b"keep")
    link = f.artifacts / "symlink"
    link.symlink_to(existing, target_is_directory=True)
    for output in (existing, tmp_path / "foreign", f.artifacts, link, f.artifacts / "nested/new"):
        with pytest.raises(backend.DeliveryError):
            builder.build(f.wheel, f.original, f.sources, output)
    assert marker.read_bytes() == b"keep"


def test_public_pins_and_apk_source_inventory_are_consistent():
    records = (ROOT / "tools/ml_runtime/source-records.json").read_bytes()
    provenance = json.loads((ROOT / "tools/ml_runtime/provenance.json").read_bytes())
    assert sha(records) == builder.RECORDS_SHA256 == provenance["source_records_sha256"]
    rows = json.loads(records)["files"]
    assert len(rows) == 45 and sum(row["filename"].endswith(".patch") for row in rows) == 44
    assert provenance["scikit_learn"]["wheel_sha256"] == backend.WHEELS["musl"][1]
    assert provenance["dependency_tag"] == builder.TAG
    for row in provenance["libraries"]:
        assert row["builder_sha256"][:8] in row["wheel_path"]
        assert row["builder_sha256"] != row["wheel_sha256"]
