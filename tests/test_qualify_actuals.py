"""Offline quality publication preserves original data and evidence availability."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from freezegun import freeze_time
import pytest

from scripts import capture_actuals, qualify_actuals


def cli_case(tmp_path, *, verified=True, normalized_input=False):
    from tests.test_actual_quality import quality_case

    events, bindings, mappings, start, end, as_of = quality_case()
    bindings = deepcopy(bindings)
    if not verified:
        bindings["bindings"][0]["qualification"]["meter"] = {"verified": False, "evidence": None, "validated_at": None}
    statistics, metadata = {}, []
    for mapping in mappings:
        for statistic in mapping["statistic_ids"]:
            metadata.append({"statistic_id": statistic, "has_sum": True, "unit_class": "energy",
                             "statistics_unit_of_measurement": "kWh"})
            rows, cursor = [], start - timedelta(hours=1)
            while cursor < end:
                rows.append({"start": cursor.timestamp() * 1000,
                             "end": (cursor + timedelta(hours=1)).timestamp() * 1000, "change": 1.0})
                cursor += timedelta(hours=1)
            statistics[statistic] = rows
    capture = capture_actuals.build_raw_capture(metadata, statistics, mappings, start, end, as_of)
    if normalized_input:
        mask = {"schema_version": 1, "validated": True,
                "provenance": {"source": "old independently asserted mask", "validated_at": as_of.isoformat()},
                "intervals": [{"inverter_id": mapping["inverter_id"], "start": start.isoformat(), "end": end.isoformat(),
                               "quality": "valid", "complete_coverage": True, "curtailed": False, "counter_reset": False}
                              for mapping in mappings]}
        capture = capture_actuals.normalize_capture(capture, mask, normalized_at=as_of)
        assert capture["normalization"]["records"]
    paths = {name: tmp_path / (name + ".json") for name in ("events", "bindings", "capture", "report", "quality", "normalized")}
    for name, value in (("events", events), ("bindings", bindings), ("capture", capture)):
        paths[name].write_text(json.dumps(value))
    args = ["qualify_actuals.py", "--events-json", str(paths["events"]), "--bindings", str(paths["bindings"]),
            "--actual-capture", str(paths["capture"]), "--as-of", as_of.isoformat(), "--output", str(paths["report"]),
            "--quality-output", str(paths["quality"]), "--normalized-output", str(paths["normalized"])]
    return paths, args, capture, as_of


@freeze_time("2026-06-03T12:00:00Z")
def test_real_quality_reaches_normalization_with_new_revision_and_unchanged_raw(tmp_path, monkeypatch, capsys):
    paths, args, capture, as_of = cli_case(tmp_path)
    originals = {name: paths[name].read_bytes() for name in ("events", "bindings", "capture")}
    monkeypatch.setattr(sys, "argv", args)
    assert qualify_actuals.main() == 0
    report = json.loads(paths["report"].read_text())
    mask = json.loads(paths["quality"].read_text())
    normalized = json.loads(paths["normalized"].read_text())
    assert report["normalization_comparison"]["raw_without_quality"]["accepted_records"] == 0
    assert report["normalization_comparison"]["derived_quality"]["accepted_records"] > 0
    assert normalized["raw"] == capture["raw"]
    assert normalized["retrieved_at"] == capture["retrieved_at"]
    generated = datetime.now(UTC).isoformat()
    assert mask["provenance"]["validated_at"] == normalized["normalized_at"] == report["generated_at"] == generated
    assert mask["provenance"]["validated_at"] != as_of.isoformat()
    assert all(row["observed_at"] == generated for row in normalized["normalization"]["records"])
    assert capture_actuals.actual_records_from_captures([normalized], as_of=as_of) == []
    assert capture_actuals.actual_records_from_captures([normalized], as_of=datetime.now(UTC))
    assert normalized["quality"] == report["quality"] == mask
    assert report["adapter_source_sha256"] and report["normalizer_source_sha256"] and report["script_sha256"]
    for name, raw in originals.items():
        assert paths[name].read_bytes() == raw
    for item in report["input_files"]:
        name = "capture" if item["role"] == "actual_capture" else item["role"]
        assert item["sha256"] == hashlib.sha256(originals[name]).hexdigest()
        assert item["bytes"] == len(originals[name])
    printed = json.loads(capsys.readouterr().out)
    assert set(printed) == {"status", "accepted_records", "excluded_records"}


@freeze_time("2026-06-03T12:00:00Z")
@pytest.mark.parametrize("normalized_input", [False, True])
def test_missing_qualification_never_reuses_an_old_positive_mask(tmp_path, monkeypatch, normalized_input):
    paths, args, _, _ = cli_case(tmp_path, verified=False, normalized_input=normalized_input)
    original = paths["capture"].read_bytes()
    monkeypatch.setattr(sys, "argv", args)
    assert qualify_actuals.main() == 0
    report = json.loads(paths["report"].read_text())
    derived = json.loads(paths["normalized"].read_text())
    assert report["normalization_comparison"]["derived_quality"]["accepted_records"] == 0
    assert derived["normalization"]["records"] == []
    assert paths["capture"].read_bytes() == original


@freeze_time("2026-06-03T12:00:00Z")
@pytest.mark.parametrize(("field", "value"), [("quality", "invalid"), ("quality", "unknown"),
                                              ("complete_coverage", False), ("curtailed", True),
                                              ("curtailed", None), ("counter_reset", True), ("counter_reset", None)])
def test_existing_negative_quality_needs_separate_resolution(tmp_path, monkeypatch, capsys, field, value):
    paths, args, capture, as_of = cli_case(tmp_path, normalized_input=True)
    capture["quality"]["intervals"][0][field] = value
    capture = capture_actuals.normalize_capture(capture, capture["quality"], normalized_at=as_of)
    paths["capture"].write_text(json.dumps(capture))
    for name in ("report", "quality", "normalized"):
        paths[name].write_text("existing result must remain unchanged")
    originals = {name: path.read_bytes() for name, path in paths.items()}

    def unexpected(*args, **kwargs):
        raise AssertionError("conflicting original quality must be checked before new qualification")

    monkeypatch.setattr(qualify_actuals.actual_quality, "build_quality", unexpected)
    monkeypatch.setattr(sys, "argv", args)
    assert qualify_actuals.main() == 2
    assert "separate explicit resolution is required" in capsys.readouterr().err
    assert all(path.read_bytes() == originals[name] for name, path in paths.items())


@freeze_time("2026-06-03T12:00:00Z")
def test_standalone_existing_negative_mask_is_not_discarded(tmp_path, monkeypatch):
    paths, args, capture, _ = cli_case(tmp_path, normalized_input=True)
    capture.pop("normalization")
    capture.pop("normalized_at")
    capture["quality"]["intervals"][0]["curtailed"] = True
    paths["capture"].write_text(json.dumps(capture))
    original = paths["capture"].read_bytes()
    monkeypatch.setattr(sys, "argv", args)
    assert qualify_actuals.main() == 2
    assert not paths["report"].exists()
    assert paths["capture"].read_bytes() == original


@freeze_time("2026-06-03T12:00:00Z")
@pytest.mark.parametrize("mode", ["altered_values", "missing_derivation", "missing_timestamp", "malformed_mask",
                                  "mask_after_cutoff", "mask_in_future", "normalization_in_future"])
def test_malformed_or_future_existing_quality_is_not_silently_replaced(tmp_path, monkeypatch, mode):
    paths, args, capture, as_of = cli_case(tmp_path, normalized_input=True)
    if mode == "altered_values":
        capture["normalization"]["records"][0]["power_w"] += 1
    elif mode == "missing_derivation":
        capture.pop("normalization")
    elif mode == "missing_timestamp":
        capture.pop("normalized_at")
    elif mode == "malformed_mask":
        capture["quality"]["validated"] = False
    else:
        changed_at = as_of + timedelta(seconds=1) if mode == "mask_after_cutoff" else datetime.now(UTC) + timedelta(seconds=1)
        if mode != "normalization_in_future":
            capture["quality"]["provenance"]["validated_at"] = changed_at.isoformat()
        capture = capture_actuals.normalize_capture(capture, capture["quality"], normalized_at=changed_at)
    paths["capture"].write_text(json.dumps(capture))
    original = paths["capture"].read_bytes()
    monkeypatch.setattr(sys, "argv", args)
    assert qualify_actuals.main() == 2
    assert not any(paths[name].exists() for name in ("report", "quality", "normalized"))
    assert paths["capture"].read_bytes() == original


def test_new_quality_timestamp_follows_input_reading_and_validation(tmp_path, monkeypatch):
    with freeze_time("2026-06-03T12:00:00Z") as clock:
        paths, args, _, _ = cli_case(tmp_path)
        original_read = qualify_actuals._read_json
        original_validate = qualify_actuals._validate_existing_quality
        entered_at = datetime.now(UTC)

        def delayed_read(*values, **kwargs):
            clock.tick(timedelta(seconds=10))
            return original_read(*values, **kwargs)

        def delayed_validation(*values, **kwargs):
            original_validate(*values, **kwargs)
            clock.tick(timedelta(seconds=10))

        monkeypatch.setattr(qualify_actuals, "_read_json", delayed_read)
        monkeypatch.setattr(qualify_actuals, "_validate_existing_quality", delayed_validation)
        monkeypatch.setattr(sys, "argv", args)
        assert qualify_actuals.main() == 0
        report = json.loads(paths["report"].read_text())
        assert datetime.fromisoformat(report["generated_at"]) > entered_at
        assert report["quality"]["provenance"]["validated_at"] == datetime.now(UTC).isoformat()


@freeze_time("2026-06-03T12:00:00Z")
@pytest.mark.parametrize("mode", ["future_cutoff", "late_raw_receipt", "malformed_raw", "backdate_option"])
def test_invalid_time_and_raw_contract_fail_without_outputs(tmp_path, monkeypatch, mode):
    paths, args, capture, as_of = cli_case(tmp_path)
    if mode == "future_cutoff":
        args[args.index("--as-of") + 1] = (datetime.now(UTC) + timedelta(seconds=1)).isoformat()
    elif mode == "late_raw_receipt":
        capture["retrieved_at"] = (as_of + timedelta(seconds=1)).isoformat()
        paths["capture"].write_text(json.dumps(capture))
    elif mode == "malformed_raw":
        capture["raw"]["timestamp_unit"] = "seconds"
        paths["capture"].write_text(json.dumps(capture))
    else:
        args += ["--generated-at", as_of.isoformat()]
    monkeypatch.setattr(sys, "argv", args)
    if mode == "backdate_option":
        with pytest.raises(SystemExit) as exc:
            qualify_actuals.main()
        assert exc.value.code == 2
    else:
        assert qualify_actuals.main() == 2
    assert not any(paths[name].exists() for name in ("report", "quality", "normalized"))


@freeze_time("2026-06-03T12:00:00Z")
@pytest.mark.parametrize("mode", ["input", "input_hardlink", "output_symlink", "same_outputs", "hardlinked_outputs", "nested_outputs"])
def test_all_outputs_are_disjoint_and_cannot_replace_inputs(tmp_path, monkeypatch, mode):
    paths, args, _, _ = cli_case(tmp_path)
    original = paths["capture"].read_bytes()
    if mode == "input":
        args[args.index("--output") + 1] = str(paths["events"])
    elif mode == "input_hardlink":
        os.link(paths["capture"], paths["normalized"])
    elif mode == "output_symlink":
        paths["quality"].symlink_to(paths["bindings"])
    elif mode == "same_outputs":
        args[args.index("--quality-output") + 1] = str(paths["report"])
    elif mode == "hardlinked_outputs":
        paths["report"].write_text("retained report")
        os.link(paths["report"], paths["quality"])
    else:
        args[args.index("--quality-output") + 1] = str(paths["report"] / "mask.json")
    monkeypatch.setattr(sys, "argv", args)
    assert qualify_actuals.main() == 2
    assert paths["capture"].read_bytes() == original
    if mode == "hardlinked_outputs":
        assert paths["report"].read_text() == paths["quality"].read_text() == "retained report"


@freeze_time("2026-06-03T12:00:00Z")
def test_publication_rechecks_paths_changed_during_computation(tmp_path, monkeypatch):
    paths, args, _, _ = cli_case(tmp_path)
    original_build = qualify_actuals.actual_quality.build_quality

    def changed(*values, **kwargs):
        report = original_build(*values, **kwargs)
        paths["quality"].symlink_to(paths["capture"])
        return report

    original = paths["capture"].read_bytes()
    monkeypatch.setattr(qualify_actuals.actual_quality, "build_quality", changed)
    monkeypatch.setattr(sys, "argv", args)
    assert qualify_actuals.main() == 2
    assert not paths["report"].exists()
    assert paths["capture"].read_bytes() == original


@freeze_time("2026-06-03T12:00:00Z")
@pytest.mark.parametrize("bound", ["single", "total"])
def test_input_limits_apply_before_quality_derivation(tmp_path, monkeypatch, bound):
    paths, args, _, _ = cli_case(tmp_path)
    sizes = [paths[key].stat().st_size for key in ("events", "bindings", "capture")]
    if bound == "single":
        monkeypatch.setattr(qualify_actuals, "MAX_INPUT_BYTES", sizes[0] - 1)
    else:
        monkeypatch.setattr(qualify_actuals, "MAX_TOTAL_BYTES", sum(sizes) - 1)
    monkeypatch.setattr(sys, "argv", args)
    assert qualify_actuals.main() == 2
    assert not paths["report"].exists()


@freeze_time("2026-06-03T12:00:00Z")
def test_repeated_event_files_are_hash_bound_without_multiplying_hours(tmp_path, monkeypatch):
    paths, args, _, _ = cli_case(tmp_path)
    monkeypatch.setattr(sys, "argv", args)
    assert qualify_actuals.main() == 0
    once = json.loads(paths["report"].read_text())
    args += ["--events-json", str(paths["events"])]
    monkeypatch.setattr(sys, "argv", args)
    assert qualify_actuals.main() == 0
    repeated = json.loads(paths["report"].read_text())
    assert repeated["summary"] == once["summary"]
    assert repeated["normalization"] == once["normalization"]
    assert len(repeated["input_files"]) == len(once["input_files"]) + 1


def test_help_needs_no_home_assistant_import():
    script = Path(qualify_actuals.__file__).resolve()
    code = """
import builtins, runpy, sys
original = builtins.__import__
def checked(name, *args, **kwargs):
    if name == 'homeassistant' or name.startswith('homeassistant.'):
        raise RuntimeError('HA import forbidden for offline adapter')
    return original(name, *args, **kwargs)
builtins.__import__ = checked
script = sys.argv[1]
sys.argv = [script, '--help']
runpy.run_path(script, run_name='__main__')
"""
    result = subprocess.run([sys.executable, "-I", "-c", code, str(script)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "--actual-capture" in result.stdout and "--quality-output" in result.stdout
