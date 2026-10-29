"""Archive installations reject HA, including accidental dependency resolution."""
import json
import subprocess
import sys
import venv
import zipfile

import pytest

from scripts import install_archive_host as subject


@pytest.fixture
def isolated(tmp_path):
    target = tmp_path / "env"
    venv.EnvBuilder(with_pip=False).create(target)
    return target


def preflight(target):
    return subprocess.run([str(target / "bin/python"), "-I", "-c", subject.CHECK, str(target)],
                          capture_output=True, text=True)


def test_ha_free_environment_passes_real_preflight(isolated):
    result = preflight(isolated)
    assert result.returncode == 0
    assert json.loads(result.stdout)["homeassistant_installed"] is False


@pytest.mark.parametrize("pollution", ["homeassistant", "pytest-homeassistant-custom-component", "orphan_module"])
def test_preflight_rejects_installed_metadata_or_leftover_ha_module(isolated, pollution):
    paths = list((isolated / "lib").glob("python*/site-packages"))
    assert len(paths) == 1
    if pollution == "orphan_module":
        module = paths[0] / "homeassistant"
        module.mkdir()
        (module / "__init__.py").write_text("")
    else:
        metadata = paths[0] / (pollution.replace("-", "_") + "-1.0.dist-info")
        metadata.mkdir()
        (metadata / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {pollution}\nVersion: 1.0\n")
    assert preflight(isolated).returncode != 0


def test_update_uses_mandatory_constraints_manifest_pins_and_postflight(isolated, monkeypatch, tmp_path):
    commands = []
    pins = tmp_path / "pins.txt"
    pins.write_text("numpy==2.3.2\n")
    def checked(command, step, *, env):
        commands.append((command, step))
        assert "PYTHONPATH" not in env
    monkeypatch.setattr(subject, "checked", checked)
    monkeypatch.setenv("PYTHONPATH", "/foreign/site-packages")
    result = subject.install(isolated, constraints=pins)
    assert [step for _, step in commands] == ["preflight", "installation", "dependency check", "postflight"]
    install = commands[1][0]
    manifest = json.loads((subject.ROOT / "custom_components/adaptive_solar/manifest.json").read_text())
    assert str(subject.CONSTRAINTS) in install and str(pins) in install
    assert all(requirement in install for requirement in manifest["requirements"])
    assert str(subject.ROOT) in install
    assert not any("ha-test" in arg or "[test" in arg for arg in install)
    assert result["homeassistant_installed"] is False
    assert commands[-1][0][-1] == "runtime"
    assert result["runtime_imports_verified"] is True


def test_runtime_postflight_rejects_an_empty_venv(isolated):
    result = subprocess.run([str(isolated / "bin/python"), "-I", "-c", subject.CHECK, str(isolated), "runtime"],
                            capture_output=True, text=True)
    assert result.returncode != 0


@pytest.mark.parametrize("foreign", [False, True])
def test_runtime_postflight_checks_real_module_locations(isolated, tmp_path, foreign):
    packages = next((isolated / "lib").glob("python*/site-packages"))
    for name in ("aiohttp", "numpy", "scipy", "pvlib", "sklearn", "custom_components/adaptive_solar/core/models"):
        path = packages / (name + ".py")
        if foreign and name == "pvlib":
            path = tmp_path / "outside/pvlib.py"
            (packages / "foreign.pth").write_text(str(path.parent))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
    result = subprocess.run([str(isolated / "bin/python"), "-I", "-c", subject.CHECK, str(isolated), "runtime"],
                            capture_output=True, text=True)
    assert (result.returncode == 0) == (not foreign)
    if not foreign:
        assert json.loads(result.stdout)["runtime_imports_verified"]


def test_pip_target_and_config_cannot_redirect_a_real_install(isolated, monkeypatch, tmp_path):
    import os
    # Bootstrap pip before introducing hostile pip settings. No network needed.
    subprocess.run([str(isolated / "bin/python"), "-I", "-m", "ensurepip"],
                   check=True, capture_output=True, text=True)
    outside, configured = tmp_path / "outside-target", tmp_path / "configured-target"
    configuration = isolated / "pip.conf"
    configuration.write_text("[global]\ntarget = " + str(configured) + "\n")
    monkeypatch.setenv("PIP_TARGET", str(outside))
    monkeypatch.setenv("PIP_CONFIG_FILE", str(configuration))
    wheel = tmp_path / "archive_probe-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("archive_probe.py", "VALUE = 1\n")
        archive.writestr("archive_probe-1.0.dist-info/METADATA", "Metadata-Version: 2.1\nName: archive-probe\nVersion: 1.0\n")
        archive.writestr("archive_probe-1.0.dist-info/WHEEL", "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        archive.writestr("archive_probe-1.0.dist-info/RECORD", "")
    real = subject.checked
    def checked(command, step, *, env):
        assert env["PIP_CONFIG_FILE"] == os.devnull
        assert set(key for key in env if key.startswith("PIP_")) == {"PIP_CONFIG_FILE", "PIP_REQUIRE_VIRTUALENV"}
        if step == "installation":
            command = command[:command.index(str(subject.ROOT))] + ["--no-index", "--no-deps", str(wheel)]
        return real(command, step, env=env)
    monkeypatch.setattr(subject, "checked", checked)
    # A probe wheel is intentionally not the complete archive runtime. It must
    # not produce a false success after pip check passed in an otherwise empty venv.
    with pytest.raises(ValueError, match="postflight"):
        subject.install(isolated)
    assert not outside.exists() and not configured.exists()
    assert next((isolated / "lib").glob("python*/site-packages/archive_probe.py")).is_file()


def test_polluted_environment_stops_before_pip_install(isolated, monkeypatch):
    calls = []
    def checked(command, step, *, env):
        calls.append(step)
        raise ValueError("HA package found")
    monkeypatch.setattr(subject, "checked", checked)
    with pytest.raises(ValueError):
        subject.install(isolated)
    assert calls == ["preflight"]


def test_system_packages_and_missing_constraints_rejected_before_install(isolated, monkeypatch):
    path = isolated / "pyvenv.cfg"
    path.write_text(path.read_text().replace("include-system-site-packages = false", "include-system-site-packages = true"))
    with pytest.raises(ValueError, match="System site"):
        subject.install(isolated)
    monkeypatch.setattr(subject, "CONSTRAINTS", isolated / "missing.txt")
    with pytest.raises(ValueError, match="Mandatory"):
        subject.install(isolated)


@pytest.mark.parametrize("package", ["homeassistant", "pytest_homeassistant_custom_component"])
def test_real_pip_resolver_cannot_install_forbidden_wheel(tmp_path, package):
    wheel = tmp_path / f"{package}-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        prefix = package + "-1.0.dist-info/"
        archive.writestr(prefix + "METADATA", f"Metadata-Version: 2.1\nName: {package.replace('_', '-')}\nVersion: 1.0\n")
        archive.writestr(prefix + "WHEEL", "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        archive.writestr(prefix + "RECORD", "")
    result = subprocess.run([sys.executable, "-m", "pip", "install", "--dry-run", "--ignore-installed",
                             "--no-index", "--constraint", str(subject.CONSTRAINTS), str(wheel)],
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert "ResolutionImpossible" in result.stderr


def test_installation_error_hides_private_pip_output(monkeypatch):
    monkeypatch.setattr(subject.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(
        a[0], 1, "private-token", "private-endpoint"))
    with pytest.raises(ValueError, match="installation failed") as error:
        subject.checked(["pip"], "installation", env={})
    assert "private" not in str(error.value)
