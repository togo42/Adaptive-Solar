"""Build orchestration tests use synthetic wheels and no network/compiler/HA."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("build_haos_wheel_under_test", ROOT / "scripts/build_haos_wheel.py")
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def supported():
    return {"implementation": "cpython", "python": [3, 14, 6], "system": "linux", "machine": "x86_64",
            "soabi": "cpython-314-x86_64-linux-musl", "free_threaded": False, "musl_version": [1, 2, 5]}


def make_wheel(path, name, version, tag, *, pure=False, bundled=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = f"{name.replace('-', '_')}-{version}.dist-info"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(prefix + "/METADATA", f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n")
        archive.writestr(prefix + "/WHEEL", f"Wheel-Version: 1.0\nRoot-Is-Purelib: {str(pure).lower()}\nTag: {tag}\n")
        if bundled:
            for library in ("libgcc_s", "libgomp", "libstdc++"):
                archive.writestr(f"scikit_learn.libs/{library}-synthetic.so.1", b"synthetic library fixture, not executable")


@pytest.mark.parametrize("change", [
    {"implementation": "pypy"}, {"python": [3, 13, 9]}, {"machine": "aarch64"},
    {"system": "darwin"}, {"soabi": "cpython-314-x86_64-linux-gnu"},
    {"free_threaded": True}, {"musl_version": [1, 1, 24]}, {"musl_version": None},
])
def test_unsupported_platform_fails_before_output_or_download(monkeypatch, tmp_path, change):
    monkeypatch.setattr(builder, "detect_platform", lambda: {**supported(), **change})
    def forbidden(*args, **kwargs):
        pytest.fail("Unsupported platform must not download, create a venv or invoke tools")
    monkeypatch.setattr(builder, "urlopen", forbidden)
    monkeypatch.setattr(builder, "prerequisites", forbidden)
    monkeypatch.setattr(builder.subprocess, "run", forbidden)
    output = tmp_path / "must-not-exist"
    with pytest.raises(builder.BuildError, match="Requires normal CPython"):
        builder.build(output)
    assert not output.exists()


def test_source_hash_failure_is_closed_and_does_not_leave_a_buildable_source(monkeypatch, tmp_path):
    calls = []
    def fake_download(url, timeout):
        calls.append((url, timeout))
        return io.BytesIO(b"wrong source bytes")
    monkeypatch.setattr(builder, "urlopen", fake_download)
    destination = tmp_path / builder.SOURCE_NAME
    with pytest.raises(builder.BuildError, match="SHA256 mismatch"):
        builder.fetch_source(destination)
    assert calls == [(builder.SOURCE_URL, 30)]
    assert not destination.exists()
    assert not list(tmp_path.glob("*.download"))


def test_existing_source_and_download_staging_are_never_overwritten(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        pytest.fail("Existing source/staging must be refused before network access")
    monkeypatch.setattr(builder, "urlopen", forbidden)
    destination = tmp_path / builder.SOURCE_NAME
    destination.write_bytes(b"existing archive")
    with pytest.raises(builder.BuildError):
        builder.fetch_source(destination)
    assert destination.read_bytes() == b"existing archive"
    destination.unlink()
    staging = destination.with_suffix(destination.suffix + ".download")
    staging.write_bytes(b"earlier interrupted download")
    with pytest.raises(builder.BuildError):
        builder.fetch_source(destination)
    assert staging.read_bytes() == b"earlier interrupted download"


def test_output_guard_refuses_ha_paths_existing_directory_and_symlink(monkeypatch, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr(builder, "WORK_ROOT", work)
    foreign = tmp_path / "config/deps"
    foreign.mkdir(parents=True)
    marker = foreign / "native-core-packages.txt"
    marker.write_text("unchanged NumPy/SciPy/Pandas")
    for output in (foreign, foreign / "new", work):
        with pytest.raises(builder.BuildError):
            builder.prepare_output(output)
    existing = work / "existing"
    existing.mkdir()
    with pytest.raises(builder.BuildError):
        builder.prepare_output(existing)
    linked = work / "link"
    linked.symlink_to(foreign, target_is_directory=True)
    with pytest.raises(builder.BuildError):
        builder.prepare_output(linked)
    assert marker.read_text() == "unchanged NumPy/SciPy/Pandas"
    assert not (foreign / "new").exists()
    output = builder.prepare_output(work / "new-build")
    assert output.parent == work


@pytest.fixture
def fake_build(monkeypatch, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr(builder, "WORK_ROOT", work)
    monkeypatch.setattr(builder, "detect_platform", supported)
    monkeypatch.setattr(builder, "prerequisites", lambda: {"auditwheel": "synthetic", "tools": {"gcc": "/usr/bin/gcc", "g++": "/usr/bin/g++", "patchelf": "/usr/bin/patchelf"}})
    payload = b"synthetic sdist, never compiled"
    monkeypatch.setattr(builder, "SOURCE_SHA256", hashlib.sha256(payload).hexdigest())
    monkeypatch.setattr(builder, "urlopen", lambda *args, **kwargs: io.BytesIO(payload))
    control = SimpleNamespace(calls=[], fail_label=None, open_audit=False, wrong_source=False)
    def fake_run(argv, *, cwd, env, stdout, stderr, timeout, check):
        output = Path(cwd)
        label = Path(stdout.name).stem
        control.calls.append((label, argv, dict(env), timeout))
        assert env["PATH"].split(":")[0] == str(output / "build-venv/bin")
        assert env["TMPDIR"] == str(output / "tmp")
        assert "PIP_TARGET" not in env and "PYTHONPATH" not in env and "HA_TOKEN" not in env
        assert env["CC"] == "gcc" and env["CXX"] == "g++"
        assert "-march=native" not in env["CFLAGS"] and "-ffast-math" not in env["CXXFLAGS"]
        assert env["CFLAGS"] == env["CXXFLAGS"] == "-O2 -march=x86-64 -mtune=generic"
        assert stderr == subprocess.STDOUT and check is False
        assert not any("/config/" in str(arg) for arg in argv)
        text = "synthetic tool output\n"
        if label == "create-build-venv":
            assert "--system-site-packages" not in argv
            (output / "build-venv/bin").mkdir(parents=True)
            (output / "build-venv/bin/python").write_text("synthetic non-executable fixture")
        elif label == "build-environment":
            text = json.dumps([{"name": name, "version": version} for name, version in builder.BUILD_PINS.items()])
        elif label == "compile-wheel":
            assert "--no-build-isolation" in argv and "--no-deps" in argv
            assert "--config-settings=compile-args=-j2" in argv
            make_wheel(output / "raw/scikit_learn-1.9.1-cp314-cp314-linux_x86_64.whl", "scikit-learn", "1.9.1", "cp314-cp314-linux_x86_64")
        elif label == "repair-wheel":
            assert argv[argv.index("--plat") + 1] == "musllinux_1_2_x86_64"
            make_wheel(output / "repaired/scikit_learn-1.9.1-cp314-cp314-musllinux_1_2_x86_64.whl", "scikit-learn", "1.9.1", builder.TARGET_TAG, bundled=True)
        elif label == "audit-repaired":
            text = "External dependency remains: libgomp.so.1" if control.open_audit else "The wheel requires no external shared libraries! :)\n"
        elif label == "download-pure-runtime":
            assert "--no-deps" in argv and "--only-binary=:all:" in argv
            for name, version in builder.RUNTIME_PINS.items():
                make_wheel(output / f"runtime/{name}-{version}-py3-none-any.whl", name, version, "py3-none-any", pure=True)
        if label.startswith("install") or label.startswith("download"):
            assert argv[0] == str(output / "build-venv/bin/python")
            assert "--isolated" in argv
        stdout.write(text.encode())
        return SimpleNamespace(returncode=7 if control.fail_label == label else 0)
    monkeypatch.setattr(builder.subprocess, "run", fake_run)
    monkeypatch.setenv("PIP_TARGET", "/config/deps/forbidden")
    monkeypatch.setenv("PYTHONPATH", "/config/deps/forbidden")
    monkeypatch.setenv("HA_TOKEN", "must-not-reach-build-tools")
    monkeypatch.setenv("CC", "foreign-compiler")
    monkeypatch.setenv("CFLAGS", "-march=native")
    monkeypatch.setenv("CXXFLAGS", "-ffast-math")
    return work, control


def test_mocked_build_produces_bound_manifest_and_only_runtime_pure_companions(fake_build):
    work, control = fake_build
    report = builder.build(work / "result", timeout=60)
    assert report["status"] == "complete"
    assert report["builder_image"] == builder.BUILDER_IMAGE
    assert report["native_core_verified"] is report["model_fit_verified"] is report["synthetic_parity_verified"] is False
    assert report["repaired_audit"]["no_external_libraries"] is True
    assert [label for label, *_ in control.calls] == ["create-build-venv", "install-build-pins", "build-environment", "build-dependency-check", "compile-wheel", "audit-raw", "repair-wheel", "audit-repaired", "download-pure-runtime"]
    assert len(report["artifacts"]) == 7
    pure = [item for item in report["artifacts"] if item["kind"] == "runtime-pure"]
    assert {item["name"] for item in pure} == {"joblib", "narwhals", "threadpoolctl", "cloudpickle"}
    assert not {"numpy", "scipy", "pandas"}.intersection(item["name"] for item in report["artifacts"])
    assert len(next(item for item in report["artifacts"] if item["kind"] == "repaired-wheel")["bundled_libraries"]) == 3
    builder.validate_manifest(report, work / "result")
    for line in (work / "result/SHA256SUMS").read_text().splitlines():
        expected, name = line.split("  ", 1)
        assert builder.sha256(work / "result" / name) == expected
    assert all(record["returncode"] == 0 for record in report["commands"])


@pytest.mark.parametrize("problem", ["hash", "metadata", "escape", "inventory", "audit", "compiler_flags"])
def test_manifest_corruption_is_rejected(fake_build, problem):
    work, _ = fake_build
    report = deepcopy(builder.build(work / "result"))
    item = next(item for item in report["artifacts"] if item["kind"] == "repaired-wheel")
    if problem == "hash":
        item["sha256"] = "0" * 64
    elif problem == "metadata":
        item["tags"] = ["cp313-cp313-musllinux_1_2_x86_64"]
    elif problem == "escape":
        item["path"] = "../config/deps/should-never-be-read"
    elif problem == "inventory":
        report["artifacts"].pop()
    elif problem == "compiler_flags":
        report["compiler_flags"] = {"CFLAGS": "-march=native"}
    else:
        report["repaired_audit"]["no_external_libraries"] = False
    with pytest.raises(builder.BuildError):
        builder.validate_manifest(report, work / "result")


def test_unresolved_external_libraries_never_get_a_complete_manifest(fake_build):
    work, control = fake_build
    control.open_audit = True
    with pytest.raises(builder.BuildError, match="external shared libraries"):
        builder.build(work / "result")
    report = json.loads((work / "result/manifest.json").read_text())
    assert report["status"] == "failed"
    assert not (work / "result/SHA256SUMS").exists()
    assert not list((work / "result/runtime").iterdir())


def test_tool_failure_preserves_logs_without_running_later_stages(fake_build):
    work, control = fake_build
    control.fail_label = "install-build-pins"
    with pytest.raises(builder.BuildError, match="install-build-pins failed"):
        builder.build(work / "result")
    report = json.loads((work / "result/manifest.json").read_text())
    assert report["status"] == "failed"
    assert report["commands"][-1]["returncode"] == 7
    assert len(control.calls) == 2


def test_hash_failure_in_orchestration_runs_no_build_commands(fake_build, monkeypatch):
    work, control = fake_build
    monkeypatch.setattr(builder, "urlopen", lambda *args, **kwargs: io.BytesIO(b"changed sdist"))
    with pytest.raises(builder.BuildError, match="SHA256 mismatch"):
        builder.build(work / "result")
    assert not control.calls
    assert json.loads((work / "result/manifest.json").read_text())["status"] == "failed"


def test_real_cli_on_glibc_refuses_before_creating_output(tmp_path):
    if "musl" in (builder.sysconfig.get_config_var("SOABI") or ""):
        pytest.skip("This regression exercises the unsupported glibc host")
    output = tmp_path / "must-not-exist"
    result = subprocess.run([sys.executable, str(ROOT / "scripts/build_haos_wheel.py"), "--output", str(output)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 2
    assert "pinned official builder" in result.stderr
    assert not output.exists()


def test_tool_timeout_records_failure_and_preserves_its_log(fake_build, monkeypatch):
    work, _ = fake_build
    original = builder.subprocess.run
    def timeout_compile(argv, **kwargs):
        if Path(kwargs["stdout"].name).stem == "compile-wheel":
            kwargs["stdout"].write(b"partial compiler output\n")
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        return original(argv, **kwargs)
    monkeypatch.setattr(builder.subprocess, "run", timeout_compile)
    with pytest.raises(builder.BuildError, match="process deadline"):
        builder.build(work / "result", timeout=1)
    report = json.loads((work / "result/manifest.json").read_text())
    assert report["status"] == "failed"
    assert report["commands"][-1]["returncode"] == "timeout"
    assert (work / "result/logs/compile-wheel.log").read_text() == "partial compiler output\n"
    assert not (work / "result/SHA256SUMS").exists()


def test_native_runtime_companion_cannot_masquerade_as_pure_python(tmp_path):
    path = tmp_path / "joblib-1.6.0-py3-none-any.whl"
    make_wheel(path, "joblib", "1.6.0", "py3-none-any", pure=False)
    with pytest.raises(builder.BuildError, match="pure Python"):
        builder.wheel_metadata(path, "joblib", "1.6.0", {"py3-none-any"})
