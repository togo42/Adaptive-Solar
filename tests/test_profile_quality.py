"""Frozen-source measurement keeps evidence and real availability separate."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

from scripts import benchmark_quality, profile_quality

ROOT = Path(__file__).resolve().parents[1]


def test_worker_environment_omits_credentials_and_sets_thread_limits(monkeypatch):
    monkeypatch.setenv("PROFILE_TEST_SECRET", "synthetic-test-secret")
    monkeypatch.setenv("HTTPS_PROXY", "https://synthetic.invalid")
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "32")
    environment = profile_quality.worker_environment()
    assert "PROFILE_TEST_SECRET" not in environment and "HTTPS_PROXY" not in environment
    assert all(name in {"PATH", "LANG", "TZ", "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS",
                        "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"} or name.startswith("LC_")
               for name in environment)
    assert environment["OPENBLAS_NUM_THREADS"] == "1"


@pytest.fixture
def frozen_case(tmp_path):
    fixture = tmp_path / "fixture"
    benchmark_quality.prepare_fixture(fixture, 1, 100)
    source = tmp_path / "source"
    for folder in ("scripts", "custom_components/adaptive_solar"):
        for path in (ROOT / folder).rglob("*"):
            if path.is_file() and path.suffix in {".py", ".json"}:
                target = source / path.relative_to(ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
    return fixture, source


def arguments(fixture, source, output):
    return ["--archive", str(fixture / "archive"), "--raw", str(fixture / "raw.json"),
            "--bindings", str(fixture / "bindings.json"), "--source-root", str(source),
            "--output", str(output), "--timeout", "60"]


def test_real_clock_worker_parity_preserves_entire_frozen_input(frozen_case, tmp_path):
    fixture, source = frozen_case
    before = {p: p.read_bytes() for p in fixture.rglob("*") if p.is_file()}
    output = tmp_path / "results"
    assert profile_quality.main(arguments(fixture, source, output)) == 0
    complete = json.loads((output / "complete.json").read_text())
    assert complete["status"] == "complete" and complete["input_bytes_unchanged"]
    ordinary, phases = complete["runs"]
    assert ordinary["accepted_records"] == phases["accepted_records"] == 24
    assert ordinary["decision_sha256"] == phases["decision_sha256"]
    # Real decision completion times differ; only the stable decision comparison matches.
    assert ordinary["result_sha256"] != phases["result_sha256"]
    assert ordinary["as_of"] < phases["as_of"] <= phases["generated_at"]
    assert phases["phases"]["archive._read_original"]["calls"] == 15
    assert phases["phases"]["archive.iter_events_next"]["events_yielded"] == 1441
    assert phases["phases"]["archive._validate_original_page"]["calls"] == 15
    assert phases["phases"]["archive._validate_original_envelope"]["calls"] == 1441
    assert phases["phases"]["archive._canonical_json_bytes"]["calls"] > 0
    assert phases["phase_markers"]["derive_to_build_wall_seconds"] > 0
    assert phases["phase_markers"]["build_to_derive_end_wall_seconds"] > 0
    assert all(p.read_bytes() == contents for p, contents in before.items())
    assert all("homeassistant" not in name for name in phases["import_origins"])
    assert not list(source.rglob("*.pyc"))


def test_decisions_ignore_only_new_availability_and_preserve_source_evidence():
    result = {"raw": {"counter": 1}, "retrieved_at": "original-receipt",
              "quality_derivation": {"as_of": "old-cutoff", "generated_at": "old-completion",
                                     "configuration_evidence": [{"producer_sha256": "a" * 64}],
                                     "quality": {"intervals": [{"quality": "valid"}],
                                                 "provenance": {"validated_at": "old-completion"}}},
              "normalization": {"records": [{"observed_at": "old-completion", "energy_kwh": 1}],
                                "excluded": []}}
    later = deepcopy(result)
    later["quality_derivation"].update(as_of="new-cutoff", generated_at="new-completion")
    later["quality_derivation"]["quality"]["provenance"]["validated_at"] = "new-completion"
    later["normalization"]["records"][0]["observed_at"] = "new-completion"
    assert profile_quality.decisions(result) == profile_quality.decisions(later)
    for mutate in (
        lambda row: row.update(retrieved_at="different-original-receipt"),
        lambda row: row["raw"].update(counter=2),
        lambda row: row["quality_derivation"]["configuration_evidence"][0].update(producer_sha256="b" * 64),
        lambda row: row["normalization"]["records"][0].update(energy_kwh=2),
        lambda row: row["quality_derivation"]["quality"]["intervals"][0].update(quality="invalid"),
    ):
        changed = deepcopy(later)
        mutate(changed)
        assert profile_quality.decisions(result) != profile_quality.decisions(changed)


@pytest.mark.parametrize("target", ["archive", "source"])
def test_rejects_outputs_inside_frozen_inputs(frozen_case, target):
    fixture, source = frozen_case
    output = (fixture / "archive" if target == "archive" else source) / "results"
    with pytest.raises(SystemExit) as error:
        profile_quality.main(arguments(fixture, source, output))
    assert error.value.code == 2
    assert not output.exists()


def test_rejects_unpinned_bytecode_before_creating_output(frozen_case, tmp_path):
    fixture, source = frozen_case
    cache = source / "scripts/__pycache__"
    cache.mkdir()
    (cache / "continuous_quality.cpython-314.pyc").write_bytes(b"untrusted cache")
    output = tmp_path / "results"
    with pytest.raises(ValueError, match="[Bb]ytecode|[Cc]ache"):
        profile_quality.main(arguments(fixture, source, output))
    assert not output.exists()


def test_corrupt_original_fails_without_success_receipt(frozen_case, tmp_path):
    fixture, source = frozen_case
    original = next((fixture / "archive/originals").rglob("*.json.gz"))
    value = bytearray(original.read_bytes())
    value[0] = 0
    original.write_bytes(value)
    output = tmp_path / "results"
    with pytest.raises(subprocess.CalledProcessError):
        profile_quality.main(arguments(fixture, source, output))
    assert not (output / "complete.json").exists()


def test_hidden_worker_cannot_write_into_pinned_source(frozen_case):
    fixture, source = frozen_case
    output = source / "new-result.json"
    result = subprocess.run([sys.executable, "-I", "-B", str(ROOT / "scripts/profile_quality.py"),
                             *arguments(fixture, source, output), "--worker-mode", "ordinary",
                             "--expected-manifest", str(fixture / "fixture.json")], capture_output=True, text=True)
    assert result.returncode != 0
    assert not output.exists()


@pytest.mark.parametrize("change", ["orphan", "missing", "same_count_different_hashes"])
def test_unreconciled_originals_are_rejected_before_output(frozen_case, tmp_path, change):
    fixture, source = frozen_case
    original = next((fixture / "archive/originals").rglob("*.json.gz"))
    if change != "missing":
        orphan = fixture / "archive/originals/ff" / ("f" * 64 + ".json.gz")
        orphan.parent.mkdir(exist_ok=True)
        shutil.copyfile(original, orphan)
    if change != "orphan":
        original.unlink()
    output = tmp_path / "results"
    with pytest.raises(ValueError, match="index and original hash sets differ"):
        profile_quality.main(arguments(fixture, source, output))
    assert not output.exists()


def test_interrupted_layout_migration_keeps_identical_hash_set(frozen_case):
    fixture, source = frozen_case
    original = next((fixture / "archive/originals").rglob("*.json.gz"))
    shutil.copyfile(original, fixture / "archive/originals" / original.name)
    inventory = profile_quality.inventories(SimpleNamespace(
        archive=fixture / "archive", raw=fixture / "raw.json", bindings=fixture / "bindings.json",
        source_root=source, max_batches=50000, max_events=2000000,
        max_archive_bytes=4 * profile_quality.GIB, max_decompressed_bytes=4 * profile_quality.GIB,
    ))
    assert inventory["batches"] == 16 and inventory["indexed_batches"] == 15


def build_selection_plan(fixture, source, path):
    """Build with precisely the modules the isolated worker will consume."""
    script = """
import json, sys
from pathlib import Path
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
from scripts import profile_quality, frozen_quality_selection as selection
from custom_components.adaptive_solar.core.archive import ArchiveStore
root = Path(sys.argv[2])
class Reader(ArchiveStore):
    def __init__(self):
        self.root = root / 'archive'
        self.originals = self.root / 'originals'
    def _db(self, *args, **kwargs):
        return profile_quality.readonly_db(self.root)
reader = Reader()
query = selection.query_from_capture(json.loads((root / 'raw.json').read_text()),
                                     json.loads((root / 'bindings.json').read_text()))
plan = selection.build_plan(reader, query)
Path(sys.argv[3]).write_text(json.dumps(plan, allow_nan=False))
print(selection.plan_sha256(plan))
"""
    result = subprocess.run([sys.executable, "-I", "-B", "-c", script, str(source), str(fixture), str(path)],
                            check=True, capture_output=True, text=True, env=profile_quality.worker_environment())
    return result.stdout.strip()


def test_pinned_selection_workers_match_full_scan_and_include_verification(frozen_case, tmp_path):
    _, source = frozen_case
    fixture = tmp_path / "two-days"
    benchmark_quality.prepare_fixture(fixture, 2, 100)
    plan_path = tmp_path / "selection.json"
    pin = build_selection_plan(fixture, source, plan_path)
    before = {p: p.read_bytes() for p in fixture.rglob("*") if p.is_file()}
    baseline, selected = tmp_path / "baseline", tmp_path / "selected"
    assert profile_quality.main(arguments(fixture, source, baseline)) == 0
    assert profile_quality.main(arguments(fixture, source, selected) + [
        "--selection-plan", str(plan_path), "--selection-plan-sha256", pin]) == 0
    full = json.loads((baseline / "complete.json").read_text())
    planned = json.loads((selected / "complete.json").read_text())
    assert all(run["decision_sha256"] == full["runs"][0]["decision_sha256"] for run in planned["runs"])
    assert all(run["selection_plan_sha256"] == pin and run["selection_verification_included_in_timing"]
               and run["availability_chronology_verified"] for run in planned["runs"])
    assert all(not run["selection_status"]["active"]
               and run["selection_status"]["headroom_fallbacks"] == 0
               and run["selection_status"]["scheduled_batches"] < run["selection_status"]["candidate_batches"]
               for run in planned["runs"])
    assert (planned["runs"][1]["phases"]["archive._read_original"]["calls"]
            < full["runs"][1]["phases"]["archive._read_original"]["calls"])
    assert all(p.read_bytes() == value for p, value in before.items())
    full_manifest = json.loads((baseline / "input-manifest.json").read_text())
    planned_manifest = json.loads((selected / "input-manifest.json").read_text())
    assert "selection_plan_file_sha256" not in full_manifest
    assert planned_manifest["selection_plan_file_sha256"] == profile_quality.file_hash(plan_path)


def test_selection_plan_requires_external_pin_and_wrong_pin_never_completes(frozen_case, tmp_path):
    fixture, source = frozen_case
    plan_path = tmp_path / "selection.json"
    build_selection_plan(fixture, source, plan_path)
    output = tmp_path / "results"
    with pytest.raises(SystemExit):
        profile_quality.main(arguments(fixture, source, output) + ["--selection-plan", str(plan_path)])
    assert not output.exists()
    with pytest.raises(subprocess.CalledProcessError):
        profile_quality.main(arguments(fixture, source, output) + [
            "--selection-plan", str(plan_path), "--selection-plan-sha256", "0" * 64])
    assert not (output / "complete.json").exists()
