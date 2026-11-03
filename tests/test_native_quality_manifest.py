"""Manifest preparation binds inputs without loading or activating native code."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import stat
from types import SimpleNamespace

import pytest

from scripts import native_quality_manifest as subject


def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    original_root = Path(subject.__file__).resolve().parents[1]
    workspace = tmp_path / "workspace"
    source = workspace / "data/source"
    for name in subject.backend.SOURCE_FILES:
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original_root / name, target)
    binary = workspace / "artifacts/kernel.so"
    binary.parent.mkdir()
    binary.write_bytes(b"Explicit preparation fixture; never dynamically loaded")
    runtime = subject.backend._runtime_snapshot()
    runtime_json = workspace / "data/runtime.json"
    runtime_json.write_text(json.dumps(runtime))
    release = tmp_path / "future-host-release"
    output = workspace / "artifacts/activation.json"
    monkeypatch.setattr(subject, "ROOT", workspace)
    monkeypatch.setattr(subject.backend._native_probe, "_load_extension",
                        lambda *args: pytest.fail("Manifest preparation must not load native code"))
    return SimpleNamespace(workspace=workspace, source=source, release=release, binary=binary,
                           runtime=runtime, runtime_json=runtime_json, output=output)


def arguments(case, output=None):
    return ["--source-root", str(case.source), "--release-root", str(case.release), "--binary", str(case.binary),
            "--runtime-json", str(case.runtime_json), "--output", str(output or case.output)]


def build(case):
    return subject.build_manifest(case.source, case.release, case.binary, case.runtime)


def test_builder_pins_all_nine_source_files_binary_and_exact_runtime_without_side_effects(inputs):
    before = {name: file_sha(inputs.source / name) for name in subject.backend.SOURCE_FILES}
    runtime, binary = deepcopy(inputs.runtime), inputs.binary.read_bytes()
    manifest = build(inputs)
    assert set(manifest) == {"schema", "protocol_version", "source_root", "sources", "binary", "runtime"}
    assert manifest["schema"] == "adaptive-solar-native-quality-runtime-v1" and manifest["protocol_version"] == 2
    assert manifest["source_root"] == str(inputs.release)
    assert manifest["sources"] == before and len(before) == 9
    assert manifest["binary"] == {"path": "native/lib_archive_probe.so", "sha256": file_sha(inputs.binary)}
    assert manifest["runtime"] == runtime == inputs.runtime
    assert inputs.binary.read_bytes() == binary
    assert {name: file_sha(inputs.source / name) for name in before} == before
    assert not inputs.release.exists() and not inputs.output.exists()


def test_unrelated_data_and_runtime_aliases_do_not_change_source_scope(inputs, tmp_path):
    expected = build(inputs)
    (inputs.source / "data").symlink_to(tmp_path / "private-data", target_is_directory=True)
    (inputs.source / ".venv").symlink_to(tmp_path / "shared-runtime", target_is_directory=True)
    cache = inputs.source / "scripts/__pycache__"
    cache.mkdir()
    (cache / "unrelated.pyc").write_bytes(b"ordinary interpreter cache")
    assert build(inputs) == expected


@pytest.mark.parametrize("member", ["custom_components/adaptive_solar/core/archive.py",
                                     "custom_components/adaptive_solar/core/actual_quality.py"])
def test_unqualified_archive_or_factory_source_is_rejected_even_with_fresh_hash(inputs, member):
    (inputs.source / member).write_bytes(b"# different semantics require qualification\n")
    with pytest.raises(ValueError, match="not qualified"):
        build(inputs)


@pytest.mark.parametrize("alias", ["source_root", "source_member", "binary"])
def test_source_and_binary_aliases_are_rejected(inputs, tmp_path, alias):
    if alias == "source_root":
        source = tmp_path / "source-alias"
        source.symlink_to(inputs.source, target_is_directory=True)
        inputs.source = source
    else:
        target = inputs.binary if alias == "binary" else inputs.source / "scripts/continuous_quality.py"
        original = tmp_path / "original-input"
        target.rename(original)
        target.symlink_to(original)
    with pytest.raises(ValueError):
        build(inputs)


@pytest.mark.parametrize("change", ["implementation", "version", "soabi", "gil", "bool_gil", "python_hash", "dependencies", "extra_field"])
def test_builder_rejects_incompatible_or_incomplete_runtime_pins(inputs, change):
    if change == "implementation":
        inputs.runtime["implementation"] = "pypy"
    elif change == "version":
        inputs.runtime["version"] = "3.13.9"
    elif change == "soabi":
        inputs.runtime["soabi"] = "cpython-313-x86_64-linux-gnu"
    elif change == "gil":
        inputs.runtime["gil_disabled"] = 1
    elif change == "bool_gil":
        inputs.runtime["gil_disabled"] = False
    elif change == "python_hash":
        inputs.runtime["python_binary_sha256"] = "not-a-binary-hash"
    elif change == "dependencies":
        inputs.runtime["dependencies"].pop("numpy")
    else:
        inputs.runtime["private_token"] = "synthetic-secret"
    with pytest.raises(ValueError, match="pins"):
        build(inputs)


@pytest.mark.parametrize("release", ["relative/release", "/host/../release", "/host//release"])
def test_final_release_path_must_be_absolute_and_canonical(inputs, release):
    inputs.release = release
    with pytest.raises(ValueError, match="roots"):
        build(inputs)


@pytest.mark.parametrize("directory", ["data", "artifacts"])
def test_cli_writes_new_mode_600_manifest_and_reports_prepared_without_activation(inputs, capsys, directory):
    output = inputs.workspace / directory / "new/activation.json"
    assert subject.main(arguments(inputs, output)) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt == {"status": "prepared_not_activated", "manifest_sha256": file_sha(output),
                       "source_files": 9, "binary_sha256": file_sha(inputs.binary)}
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert json.loads(output.read_text()) == build(inputs)
    assert not inputs.release.exists()


@pytest.mark.parametrize("destination", ["existing", "runtime", "binary", "protected_source", "code", "outside"])
def test_cli_rejects_output_collisions_and_protected_paths_before_writing(inputs, tmp_path, destination):
    if destination == "existing":
        output = inputs.output
        output.write_text("preserved existing output")
    elif destination == "runtime":
        output = inputs.runtime_json
    elif destination == "binary":
        output = inputs.binary
    elif destination == "protected_source":
        # This is below allowed data/, so source protection must also apply.
        output = inputs.source / "scripts/new-output.json"
    elif destination == "code":
        output = inputs.workspace / "scripts/new-output.json"
    else:
        output = tmp_path / "unmanaged/new-output.json"
    before = output.read_bytes() if output.exists() else None
    with pytest.raises(SystemExit) as failure:
        subject.main(arguments(inputs, output))
    assert failure.value.code == 2
    assert output.read_bytes() == before if before is not None else not output.exists()
    assert not inputs.release.exists()


@pytest.mark.parametrize("failure", ["json", "private_extra", "duplicate", "symlink"])
def test_invalid_runtime_evidence_has_fixed_private_error_and_no_output(inputs, tmp_path, capsys, failure):
    secret = "synthetic-private-token-and-host-path"
    if failure == "json":
        inputs.runtime_json.write_text("invalid-json-" + secret)
    elif failure == "private_extra":
        inputs.runtime["HA_TOKEN"] = secret
        inputs.runtime_json.write_text(json.dumps(inputs.runtime))
    elif failure == "duplicate":
        inputs.runtime_json.write_text('{"implementation":"cpython","implementation":"' + secret + '"}')
    else:
        original = tmp_path / "runtime-original.json"
        inputs.runtime_json.rename(original)
        inputs.runtime_json.symlink_to(original)
    assert subject.main(arguments(inputs)) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "Native activation manifest preparation failed.\n"
    assert secret not in captured.err and not inputs.output.exists()
