#!/usr/bin/env python3
"""Build one pinned scikit-learn wheel inside the documented official HA builder.

Build artifacts only: never deploy to HA, install into /config, or replace Core
NumPy/SciPy/Pandas. The image digest is a required external launch convention;
this process verifies ABI/libc but cannot attest its own OCI image identity.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from email.parser import BytesParser
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import sysconfig
import time
from urllib.request import urlopen
import zipfile

BUILDER_IMAGE = "ghcr.io/home-assistant/wheels/amd64/musllinux_1_2/cp314:2026.10.0@sha256:65b0dfb84c7b8326fca5aa47df1f8e787f4903393f050266d2ba0c15850fd390"
SOURCE_NAME = "scikit_learn-1.9.1.tar.gz"
SOURCE_URL = "https://files.pythonhosted.org/packages/d2/eb/eaf5e07fcc0da7149b0e084f24e54edd7441b9a89ce7e034032ae97fe3a0/scikit_learn-1.9.1.tar.gz"
SOURCE_SHA256 = "629cada3e33e2b9bf376cdc7614a47a4140b8aedc1d836579e359736fbd82977"
BUILD_PINS = {"numpy": "2.3.2", "scipy": "1.18.1", "cython": "3.2.5", "meson-python": "0.21.0", "ninja": "1.13.2"}
RUNTIME_PINS = {"joblib": "1.6.0", "narwhals": "2.27.1", "threadpoolctl": "3.7.0", "cloudpickle": "3.1.2"}
COMPILER_FLAGS = {"CC": "gcc", "CXX": "g++", "CFLAGS": "-O2 -march=x86-64 -mtune=generic",
                  "CXXFLAGS": "-O2 -march=x86-64 -mtune=generic", "CPPFLAGS": "", "LDFLAGS": ""}
TARGET_TAG = "cp314-cp314-musllinux_1_2_x86_64"
WORK_ROOT = Path("/work")


class BuildError(ValueError):
    """A precondition or reproducibility gate failed."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def detect_platform() -> dict:
    info = {"implementation": sys.implementation.name, "python": list(sys.version_info[:3]),
            "system": sys.platform, "machine": platform.machine(), "soabi": sysconfig.get_config_var("SOABI"),
            "free_threaded": bool(sysconfig.get_config_var("Py_GIL_DISABLED")), "musl_version": None}
    loader = Path("/lib/ld-musl-x86_64.so.1")
    if info["system"] == "linux" and loader.is_file() and "musl" in (info["soabi"] or ""):
        result = subprocess.run([str(loader)], capture_output=True, text=True, timeout=10, check=False)
        match = re.search(r"Version (\d+)\.(\d+)\.(\d+)", result.stdout + result.stderr)
        if match:
            info["musl_version"] = [int(value) for value in match.groups()]
    return info


def validate_platform(info: dict) -> None:
    if (info.get("implementation") != "cpython" or info.get("python", [])[:2] != [3, 14]
            or info.get("system") != "linux" or info.get("machine", "").lower() not in {"x86_64", "amd64"}
            or info.get("soabi") != "cpython-314-x86_64-linux-musl" or info.get("free_threaded") is not False
            or not isinstance(info.get("musl_version"), list) or len(info["musl_version"]) != 3
            or any(type(value) is not int for value in info["musl_version"])
            or tuple(info["musl_version"]) < (1, 2, 0)):
        raise BuildError("Requires normal CPython 3.14 on Linux x86_64 with musl >=1.2; use the pinned official builder")


def prerequisites() -> dict:
    try:
        version = metadata.version("auditwheel")
    except metadata.PackageNotFoundError as exc:
        raise BuildError("The official builder must provide auditwheel") from exc
    tools = {name: shutil.which(name) for name in ("gcc", "g++", "patchelf")}
    if not all(tools.values()):
        raise BuildError("The official builder must provide gcc, g++ and patchelf")
    return {"auditwheel": version, "tools": tools}


def prepare_output(output: Path) -> Path:
    """Only create a fresh direct child of the dedicated /work mount."""
    root = WORK_ROOT.resolve(strict=True)
    if WORK_ROOT.is_symlink() or output.is_symlink() or output.exists():
        raise BuildError("Output must be a new directory; existing paths and symlinks are never reused")
    resolved = output.resolve()
    if resolved.parent != root or resolved == root:
        raise BuildError("Output must be a fresh direct child of /work, never a HA/config/dependency path")
    resolved.mkdir(mode=0o700)
    return resolved


def fetch_source(destination: Path) -> None:
    """Fixed PyPI sdist, hash-checked before any source code is built."""
    if destination.exists() or destination.is_symlink():
        raise BuildError("Source destination already exists")
    partial = destination.with_suffix(destination.suffix + ".download")
    if partial.exists() or partial.is_symlink():
        raise BuildError("Source download staging path already exists")
    started, count = time.monotonic(), 0
    try:
        with urlopen(SOURCE_URL, timeout=30) as response, partial.open("xb") as stream:
            while True:
                if time.monotonic() - started > 120:
                    raise BuildError("Source download exceeded its deadline")
                chunk = response.read1(1024 * 1024)
                if not chunk:
                    break
                count += len(chunk)
                if count > 32 * 1024 * 1024:
                    raise BuildError("Source archive exceeds its fixed download limit")
                stream.write(chunk)
        if sha256(partial) != SOURCE_SHA256:
            raise BuildError("PyPI source SHA256 mismatch; no build was started")
        partial.rename(destination)
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def build_environment(output: Path) -> dict:
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("PIP_", "HA_")) and key not in
                   {"PYTHONPATH", "PYTHONHOME", "PYTHONUSERBASE", "VIRTUAL_ENV"}}
    environment.update(PATH=str(output / "build-venv/bin") + os.pathsep + environment.get("PATH", ""),
        TMPDIR=str(output / "tmp"), PYTHONNOUSERSITE="1", PYTHONPYCACHEPREFIX=str(output / "pycache"),
        PIP_CONFIG_FILE=os.devnull, LC_ALL="C", CCACHE_DIR=str(output / "ccache"))
    environment.update(COMPILER_FLAGS)
    return environment


def wheel_metadata(path: Path, name: str, version: str, tags: set[str]) -> dict:
    """Read only metadata; never extract or execute the generated wheel here."""
    try:
        with zipfile.ZipFile(path) as wheel:
            def message(suffix):
                names = [member for member in wheel.namelist() if member.endswith(".dist-info/" + suffix)]
                if len(names) != 1 or wheel.getinfo(names[0]).file_size > 2 * 1024 * 1024:
                    raise BuildError("Wheel has ambiguous or oversized metadata")
                return BytesParser().parsebytes(wheel.read(names[0]))
            package, abi = message("METADATA"), message("WHEEL")
            actual_tags = set(abi.get_all("Tag", []))
            if (canonical_name(package.get("Name", "")) != canonical_name(name) or package.get("Version") != version
                    or not actual_tags or not actual_tags <= tags):
                raise BuildError("Wheel package/version/ABI does not match the pinned artifact")
            if tags == {"py3-none-any"} and abi.get("Root-Is-Purelib", "").lower() != "true":
                raise BuildError("Runtime companions must be pure Python wheels")
            bundled = sorted(member for member in wheel.namelist() if ".libs/" in member and ".so" in member)
            return {"name": canonical_name(name), "version": version, "tags": sorted(actual_tags), "bundled_libraries": bundled}
    except (OSError, zipfile.BadZipFile) as exc:
        raise BuildError("Wheel metadata could not be verified") from exc


def require_closed_audit(report: str) -> None:
    if "The wheel requires no external shared libraries" not in report:
        raise BuildError("Repaired auditwheel report does not prove absence of external shared libraries")


def validate_manifest(report: dict, output: Path) -> None:
    if report.get("schema_version") != 1 or report.get("status") != "complete" or report.get("builder_image") != BUILDER_IMAGE:
        raise BuildError("Invalid build manifest identity/status")
    validate_platform(report["platform"])
    if (report.get("source", {}).get("sha256") != SOURCE_SHA256 or report.get("build_pins") != BUILD_PINS
            or report.get("runtime_pins") != RUNTIME_PINS or report.get("compiler_flags") != COMPILER_FLAGS):
        raise BuildError("Build manifest pins do not match the fixed build")
    if report.get("repaired_audit", {}).get("no_external_libraries") is not True:
        raise BuildError("Build manifest lacks the repaired-library gate")
    artifacts = report.get("artifacts", [])
    expected = {("source", "scikit-learn"), ("raw-wheel", "scikit-learn"), ("repaired-wheel", "scikit-learn"),
                *(("runtime-pure", name) for name in RUNTIME_PINS)}
    if {(item.get("kind"), item.get("name")) for item in artifacts} != expected or len(artifacts) != len(expected):
        raise BuildError("Build manifest artifact inventory is incomplete or ambiguous")
    for item in artifacts:
        relative = Path(item["path"])
        path = output / relative
        if relative.is_absolute() or ".." in relative.parts or path.is_symlink() or not path.resolve().is_relative_to(output):
            raise BuildError("Build manifest artifact escapes its output directory")
        if not path.is_file() or path.stat().st_size != item["size"] or sha256(path) != item["sha256"]:
            raise BuildError("Build manifest artifact size/hash mismatch")
        if item["kind"] == "source":
            if item["sha256"] != SOURCE_SHA256 or item.get("version") != "1.9.1":
                raise BuildError("Build manifest source artifact differs from the pinned source")
        else:
            version = RUNTIME_PINS[item["name"]] if item["kind"] == "runtime-pure" else "1.9.1"
            allowed = {"py3-none-any"} if item["kind"] == "runtime-pure" else {TARGET_TAG}
            if item["kind"] == "raw-wheel":
                allowed.add("cp314-cp314-linux_x86_64")
            details = wheel_metadata(path, item["name"], version, allowed)
            if any(item.get(key) != details[key] for key in ("version", "tags", "bundled_libraries")):
                raise BuildError("Build manifest wheel metadata differs from the actual wheel")


def build(output: Path, timeout: int = 3600) -> dict:
    if type(timeout) is not int or not 1 <= timeout <= 7200:
        raise BuildError("Per-command timeout must be an integer from 1 to 7200 seconds")
    info = detect_platform()
    validate_platform(info)  # No directories, downloads or builds on an unsupported host.
    tool_info = prerequisites()
    output = prepare_output(output)
    for name in ("src", "raw", "repaired", "runtime", "logs", "tmp"):
        (output / name).mkdir()
    report = {"schema_version": 1, "status": "building", "started_at": datetime.now(timezone.utc).isoformat(),
        "builder_image": BUILDER_IMAGE, "image_identity_evidence": "pinned launch command required; not attested inside container",
        "helper_sha256": sha256(Path(__file__)), "platform": info, "builder_tools": tool_info,
        "source": {"url": SOURCE_URL, "filename": SOURCE_NAME, "sha256": SOURCE_SHA256},
        "build_pins": BUILD_PINS, "runtime_pins": RUNTIME_PINS, "compiler_flags": COMPILER_FLAGS, "commands": [], "artifacts": [],
        "native_core_verified": False, "model_fit_verified": False, "synthetic_parity_verified": False}
    def save():
        (output / "manifest.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    environment = build_environment(output)
    def step(label, argv):
        log = output / "logs" / (label + ".log")
        record = {"label": label, "argv": [str(arg) for arg in argv], "timeout_seconds": timeout,
                  "log": str(log.relative_to(output))}
        report["commands"].append(record)
        save()
        print(label, flush=True)
        try:
            with log.open("wb") as stream:
                result = subprocess.run(record["argv"], cwd=output, env=environment, stdout=stream,
                                        stderr=subprocess.STDOUT, timeout=timeout, check=False)
            record["returncode"] = result.returncode
        except subprocess.TimeoutExpired as exc:
            record["returncode"] = "timeout"
            raise BuildError(f"{label} exceeded its process deadline") from exc
        finally:
            if log.exists():
                record["log_sha256"] = sha256(log)
            save()
        if result.returncode:
            raise BuildError(f"{label} failed; inspect its output log")
        return log
    def artifact(path, kind, details):
        report["artifacts"].append({"kind": kind, "path": str(path.relative_to(output)),
            "sha256": sha256(path), "size": path.stat().st_size, **details})
    python = output / "build-venv/bin/python"
    pip = [str(python), "-m", "pip", "--isolated", "--disable-pip-version-check", "--no-cache-dir"]
    try:
        save()
        source = output / "src" / SOURCE_NAME
        fetch_source(source)
        artifact(source, "source", {"name": "scikit-learn", "version": "1.9.1"})
        step("create-build-venv", [sys.executable, "-I", "-m", "venv", str(output / "build-venv")])
        step("install-build-pins", [*pip, "install", "--only-binary=:all:", "--index-url", "https://pypi.org/simple",
            *(f"{name}=={version}" for name, version in BUILD_PINS.items())])
        log = step("build-environment", [*pip, "list", "--format=json"])
        packages = json.loads(log.read_text())
        versions = {canonical_name(row["name"]): row["version"] for row in packages}
        if any(versions.get(name) != version for name, version in BUILD_PINS.items()):
            raise BuildError("Installed build environment does not match the pinned versions")
        report["resolved_build_packages"] = versions
        step("build-dependency-check", [*pip, "check"])
        step("compile-wheel", [*pip, "wheel", "--no-deps", "--no-build-isolation", "--wheel-dir", str(output / "raw"),
            "--config-settings=compile-args=-j2", str(source)])
        raw = list((output / "raw").glob("*.whl"))
        if len(raw) != 1:
            raise BuildError("Expected exactly one raw scikit-learn wheel")
        raw = raw[0]
        details = wheel_metadata(raw, "scikit-learn", "1.9.1", {TARGET_TAG, "cp314-cp314-linux_x86_64"})
        artifact(raw, "raw-wheel", details)
        step("audit-raw", [sys.executable, "-m", "auditwheel", "show", str(raw)])
        step("repair-wheel", [sys.executable, "-m", "auditwheel", "repair", "--plat", "musllinux_1_2_x86_64",
            "--wheel-dir", str(output / "repaired"), str(raw)])
        repaired = list((output / "repaired").glob("*.whl"))
        if len(repaired) != 1:
            raise BuildError("Expected exactly one repaired scikit-learn wheel")
        repaired = repaired[0]
        details = wheel_metadata(repaired, "scikit-learn", "1.9.1", {TARGET_TAG})
        artifact(repaired, "repaired-wheel", details)
        log = step("audit-repaired", [sys.executable, "-m", "auditwheel", "show", str(repaired)])
        require_closed_audit(log.read_text())
        report["repaired_audit"] = {"no_external_libraries": True, "log": str(log.relative_to(output))}
        step("download-pure-runtime", [*pip, "download", "--only-binary=:all:", "--no-deps", "--index-url", "https://pypi.org/simple",
            "--dest", str(output / "runtime"), *(f"{name}=={version}" for name, version in RUNTIME_PINS.items())])
        wheels = list((output / "runtime").glob("*.whl"))
        if len(wheels) != len(RUNTIME_PINS):
            raise BuildError("Expected only the four pinned pure-Python companion wheels")
        found = set()
        for wheel in wheels:
            match = next((name for name in RUNTIME_PINS if wheel.name.startswith(name.replace("-", "_") + "-")), None)
            if match is None or match in found:
                raise BuildError("Unexpected or duplicate pure-Python companion")
            found.add(match)
            artifact(wheel, "runtime-pure", wheel_metadata(wheel, match, RUNTIME_PINS[match], {"py3-none-any"}))
        report.update(status="complete", finished_at=datetime.now(timezone.utc).isoformat())
        validate_manifest(report, output)
        save()
        paths = sorted(item["path"] for item in report["artifacts"]) + ["manifest.json"]
        (output / "SHA256SUMS").write_text("".join(f"{sha256(output / path)}  {path}\n" for path in paths))
        return report
    except Exception as exc:
        report.update(status="failed", error=str(exc) if isinstance(exc, BuildError) else "Build input/output or tool execution failed")
        save()
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("/work/haos-wheel-output"), help="New direct child of /work")
    parser.add_argument("--timeout", type=int, default=3600, help="Per-command deadline in seconds (maximum 7200)")
    args = parser.parse_args()
    try:
        build(args.output, args.timeout)
    except (BuildError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(str(exc) if isinstance(exc, BuildError) else "Wheel build failed; inspect the build manifest/logs", file=sys.stderr)
        return 2
    print("Build complete. Verify manifest/SHA256SUMS and test separately; no HA installation was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
