"""Real offline command processes; socket access is forbidden in every child."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def offline_process(tmp_path):
    hook_dir = tmp_path / "network_guard"
    hook_dir.mkdir()
    attempts = tmp_path / "network-attempted.txt"
    ready = tmp_path / "network-guard-ready.txt"
    (hook_dir / "sitecustomize.py").write_text('''
import os
from pathlib import Path
import socket
Path(os.environ["CLI_GUARD_READY"]).write_text("enabled")
def blocked(*args, **kwargs):
    Path(os.environ["CLI_NETWORK_ATTEMPTS"]).write_text("unexpected network attempt")
    raise RuntimeError("Network is forbidden in CLI end-to-end tests")
socket.socket.connect = blocked
socket.socket.connect_ex = blocked
socket.create_connection = blocked
socket.getaddrinfo = blocked
''')
    env = {**os.environ, "PYTHONPATH": str(hook_dir),
           "CLI_NETWORK_ATTEMPTS": str(attempts), "CLI_GUARD_READY": str(ready)}

    def run(script, *args):
        completed = subprocess.run([sys.executable, str(ROOT / "scripts" / script), *map(str, args)],
                                   cwd=tmp_path, env=env, capture_output=True, text=True, timeout=40)
        assert ready.read_text() == "enabled"
        assert not attempts.exists(), "The command attempted a network connection"
        return completed
    return run


@pytest.mark.parametrize("issued_string", [
    "2026-06-21T09:35:00+02:00",  # summertime offset
    "2026-10-24T12:35:00+02:00",  # includes 25-hour local DST day
    "2026-03-28T12:35:00+01:00",  # includes 23-hour local DST day
])
def test_forecast_cli_offline_example_preserves_offsets_and_dst(offline_process, tmp_path, issued_string):
    output = tmp_path / "nested" / "forecast.json"
    run = offline_process("forecast.py", "--config", ROOT / "examples/site.json", "--synthetic",
                          "--as-of", issued_string, "--output", output)
    assert run.returncode == 0, run.stderr
    payload = json.loads(output.read_text())
    assert payload["evidence"] == "synthetic_clear_sky_demo"
    forecast = payload["forecast"]
    issued = datetime.fromisoformat(issued_string)
    assert datetime.fromisoformat(forecast["issued_at"]) == issued
    config = json.loads((ROOT / "examples/site.json").read_text())
    assert len(config["strings"]) == 3
    assert {s["azimuth_deg"] for s in config["strings"]} == {90, 180, 270}
    zone = ZoneInfo(config["timezone"])
    local = issued.astimezone(zone)
    end = datetime.combine(local.date() + timedelta(days=config["forecast_days"]), datetime.min.time(), zone)
    start = issued.astimezone(timezone.utc)
    source_start = start.replace(minute=0, second=0, microsecond=0)
    expected_hours = int((end.astimezone(timezone.utc) - source_start).total_seconds() / 3600)
    assert len(forecast["points"]) == expected_hours * len(config["inverters"])
    for inverter in config["inverters"]:
        points = [p for p in forecast["points"] if p["inverter_id"] == inverter["id"]]
        assert datetime.fromisoformat(points[0]["start"]) == start
        assert datetime.fromisoformat(points[0]["end"]) == source_start + timedelta(hours=1)
        assert points[0]["features"]["source_partial_at_issue"] == 1
        assert datetime.fromisoformat(points[-1]["end"]) == end
        assert all(a["end"] == b["start"] for a, b in zip(points, points[1:]))
        assert all(0 <= p["power_w"] <= inverter["max_ac_kw"] * 1000 for p in points)
        assert any(p["power_w"] > 0 for p in points)
        assert any(p["power_w"] == 0 for p in points)
    assert forecast["model_status"]["weather:ecmwf_ifs025"] == "unavailable"


def test_forecast_cli_shared_inverter_clips_once_after_unequal_strings(offline_process, tmp_path):
    config = json.loads((ROOT / "examples/site.json").read_text())
    config["forecast_days"] = 1
    # Both large east/west strings share this small AC budget.
    config["inverters"][0]["max_ac_kw"] = 0.5
    config_path = tmp_path / "site.json"
    config_path.write_text(json.dumps(config))
    output = tmp_path / "forecast.json"
    run = offline_process("forecast.py", "--config", config_path, "--synthetic",
                          "--as-of", "2026-06-21T00:00:00+02:00", "--output", output)
    assert run.returncode == 0, run.stderr
    points = json.loads(output.read_text())["forecast"]["points"]
    roof = [p for p in points if p["inverter_id"] == "roof"]
    assert max(p["power_w"] for p in roof) == 500
    assert max(p["baseline_w"] for p in roof) == 500
    # Two roof strings still produce one inverter interval per hour.
    assert len(roof) == 24
    assert len({(p["start"], p["end"]) for p in roof}) == 24


def test_forecast_cli_dc_example_reports_declared_boundary_and_shared_output_cap(offline_process, tmp_path):
    output = tmp_path / "dc.json"
    run = offline_process("forecast.py", "--config", ROOT / "examples/site-dc.json", "--synthetic",
                          "--as-of", "2026-06-21T00:00:00+02:00", "--output", output)
    assert run.returncode == 0, run.stderr
    payload = json.loads(output.read_text())
    assert payload["evidence"] == "synthetic_clear_sky_demo"
    assert payload["outputs"] == {"controller": {"output_type": "dc",
        "measurement_boundary": "dc_charge_controller_output", "nominal_output_cap_w": 2500}}
    points = payload["forecast"]["points"]
    assert len(points) == 24 and {p["inverter_id"] for p in points} == {"controller"}
    assert max(p["power_w"] for p in points) == 2500
    assert all(0 <= p["power_w"] <= 2500 for p in points)
    assert any(p["power_w"] == 0 for p in points)


@pytest.mark.parametrize("as_of", ["2026-06-21T00:00:00+02:00", ""])
def test_forecast_cli_live_backdating_is_refused_before_io(offline_process, tmp_path, as_of):
    output = tmp_path / "must-not-exist.json"
    run = offline_process("forecast.py", "--config", tmp_path / "also-does-not-exist.json", "--live",
                          "--as-of", as_of, "--output", output)
    assert run.returncode == 2
    assert "Live forecasts cannot be backdated" in run.stderr
    assert not output.exists()


def test_forecast_cli_rejects_naive_as_of_without_network(offline_process, tmp_path):
    output = tmp_path / "forecast.json"
    run = offline_process("forecast.py", "--config", ROOT / "examples/site.json", "--synthetic",
                          "--as-of", "2026-06-21T00:00:00", "--output", output)
    assert run.returncode == 2
    assert "explicit timezone" in run.stderr
    assert not output.exists()


def test_evaluate_cli_preserves_missing_actual_and_refuses_skill_claim(offline_process, tmp_path):
    start, end = "2026-06-21T10:00:00+02:00", "2026-06-21T11:00:00+02:00"
    cutoff, as_of = "2026-06-21T09:00:00+02:00", "2026-06-21T12:00:00+02:00"
    payload = {"as_of": as_of, "timezone_name": "Europe/Berlin", "sources": ["adaptive", "physics"],
               "windows": [{"cutoff": cutoff, "start": start, "end": end, "inverter_id": "roof", "daylight": True}],
               "actuals": [{"start": start, "end": end, "inverter_id": "roof", "power_w": None, "observed_at": as_of}],
               "forecasts": [{"source": source, "issued_at": cutoff, "start": start, "end": end,
                              "inverter_id": "roof", "power_w": power}
                             for source, power in (("adaptive", 1000), ("physics", 1200))]}
    source = tmp_path / "archive.json"
    source.write_text(json.dumps(payload))
    output = tmp_path / "nested" / "evaluation.json"
    run = offline_process("evaluate.py", source, "--output", output)
    assert run.returncode == 0, run.stderr
    report = json.loads(output.read_text())
    assert report["expected_intervals"] == 1
    assert report["paired_intervals"] == 0
    assert report["coverage"] == 0
    assert not report["comparison_eligible"]
    assert report["missing"][0]["missing_actual"] is True
    assert report["missing"][0]["missing_sources"] == []
    assert report["excluded"] == {"missing_actual": 1}
    for scores in report["scores"].values():
        assert scores["overall"]["actual_energy_kwh"] is None
        assert scores["overall"]["mae_w"] is None
    assert not report["improvement"]["physics"]["supports_improvement_on_paired_archive"]
    assert "0/1 paired intervals" in run.stdout


def test_forecast_cli_invalid_as_of_is_clear_argument_error(offline_process, tmp_path):
    output = tmp_path / "forecast.json"
    run = offline_process("forecast.py", "--config", ROOT / "examples/site.json", "--synthetic",
                          "--as-of", "not-a-date", "--output", output)
    assert run.returncode == 2
    assert "valid ISO timestamp" in run.stderr
    assert "Traceback" not in run.stderr
    assert not output.exists()


@pytest.mark.parametrize("outage_issue,expected_pairs", [
    ("2026-06-21T08:45:00+02:00", 0),
    ("2026-06-21T09:01:00+02:00", 1),
])
def test_evaluate_cli_capture_outage_blocks_old_success_only_at_eligible_cutoff(offline_process, tmp_path, outage_issue, expected_pairs):
    start, end = "2026-06-21T10:00:00+02:00", "2026-06-21T11:00:00+02:00"
    cutoff, old_issue = "2026-06-21T09:00:00+02:00", "2026-06-21T08:00:00+02:00"
    payload = {"as_of": "2026-06-21T12:00:00+02:00", "sources": ["adaptive", "helios"],
               "windows": [{"cutoff": cutoff, "start": start, "end": end, "inverter_id": "roof"}],
               "actuals": [{"start": start, "end": end, "inverter_id": "roof", "power_w": 1000,
                            "observed_at": "2026-06-21T11:00:00+02:00"}]}
    def group(source, issue, power=None):
        rows = [] if power is None else [{"source": source, "inverter_id": "roof", "issued_at": issue,
            "retrieved_at": issue, "start": start, "end": end, "power_w": power, "energy_wh": power}]
        return {"source": source, "inverter_id": "roof", "issued_at": issue, "retrieved_at": issue,
                "status": "missing_entries" if power is None else "available", "records": rows}
    captures = [{"schema_version": 1, "groups": [group("adaptive", old_issue, 1000), group("helios", old_issue, 1200)]},
                {"schema_version": 1, "groups": [group("helios", outage_issue)]}]
    archive = tmp_path / "captures.jsonl"
    archive.write_text("".join(json.dumps(captured) + "\n" for captured in captures))
    schedule = tmp_path / "schedule.json"
    schedule.write_text(json.dumps(payload))
    output = tmp_path / "report.json"
    run = offline_process("evaluate.py", schedule, "--captures", archive, "--output", output)
    assert run.returncode == 0, run.stderr
    report = json.loads(output.read_text())
    assert report["paired_intervals"] == expected_pairs
    if not expected_pairs:
        assert report["missing"][0]["missing_sources"] == ["helios"]
        assert report["scores"]["helios"]["overall"]["mae_w"] is None
    else:
        assert report["scores"]["helios"]["overall"]["mae_w"] == 200


def test_evaluate_cli_malformed_capture_is_not_silently_skipped(offline_process, tmp_path):
    schedule = tmp_path / "schedule.json"
    schedule.write_text(json.dumps({"as_of": "2026-06-21T12:00:00+02:00", "windows": [], "actuals": []}))
    archive = tmp_path / "captures.jsonl"
    archive.write_text('{"schema_version":1,"groups":[]}\n{"truncated":')
    output = tmp_path / "report.json"
    run = offline_process("evaluate.py", schedule, "--captures", archive, "--output", output)
    assert run.returncode != 0
    assert not output.exists()


def test_evaluate_cli_cannot_overwrite_its_capture_archive(offline_process, tmp_path):
    schedule = tmp_path / "schedule.json"
    schedule.write_text('{}')
    archive = tmp_path / "capture.jsonl"
    original = '{"schema_version":1,"groups":[]}\n'
    archive.write_text(original)
    run = offline_process("evaluate.py", schedule, "--captures", archive, "--output", archive)
    assert run.returncode == 2
    assert "must not overwrite an input archive" in run.stderr
    assert archive.read_text() == original


@pytest.mark.parametrize("alias", ["same_path", "symlink", "hardlink"])
def test_forecast_cli_cannot_overwrite_configuration_through_alias(offline_process, tmp_path, alias):
    config = tmp_path / "site.json"
    original = (ROOT / "examples/site.json").read_bytes()
    config.write_bytes(original)
    output = config if alias == "same_path" else tmp_path / "output.json"
    if alias == "symlink":
        output.symlink_to(config)
    elif alias == "hardlink":
        os.link(config, output)
    run = offline_process("forecast.py", "--config", config, "--synthetic",
                          "--as-of", "2026-06-21T00:00:00+02:00", "--output", output)
    assert run.returncode == 2
    assert "must not overwrite the configuration" in run.stderr
    assert config.read_bytes() == original


def evaluation_payload(*, include_actuals=False):
    start = datetime(2026, 6, 21, 10, tzinfo=timezone.utc)
    end, issue = start + timedelta(hours=1), start - timedelta(hours=1)
    payload = {"as_of": (end + timedelta(hours=1)).isoformat(),
               "sources": ["adaptive", "helios", "open_meteo"],
               "windows": [{"cutoff": issue.isoformat(), "start": start.isoformat(), "end": end.isoformat(),
                            "inverter_id": "roof"}],
               "forecasts": [{"source": source, "issued_at": issue.isoformat(), "start": start.isoformat(),
                              "end": end.isoformat(), "inverter_id": "roof", "power_w": power}
                             for source, power in (("adaptive", 1000), ("helios", 1200), ("open_meteo", 1300))]}
    if include_actuals:
        payload["actuals"] = [{"start": start.isoformat(), "end": end.isoformat(), "inverter_id": "roof",
                               "power_w": 1000, "observed_at": end.isoformat()}]
    return payload


def actual_capture(*, quality_status="valid"):
    from scripts.capture_actuals import build_raw_capture, normalize_capture

    start = datetime(2026, 6, 21, 10, tzinfo=timezone.utc)
    end, received = start + timedelta(hours=1), start + timedelta(hours=2)
    metadata = [{"statistic_id": "sensor.energy", "has_sum": True,
                 "unit_class": "energy", "unit_of_measurement": "kWh"}]
    statistics = {"sensor.energy": [{"start": (start + timedelta(hours=offset)).timestamp() * 1000,
                                     "end": (end + timedelta(hours=offset)).timestamp() * 1000,
                                     "change": 1.0} for offset in (-1, 0)]}
    raw = build_raw_capture(metadata, statistics, [{"inverter_id": "roof", "statistic_ids": ["sensor.energy"]}],
                            start, end, received)
    quality = {"schema_version": 1, "validated": True,
               "provenance": {"source": "synthetic-test-coverage", "validated_at": received.isoformat()},
               "intervals": [{"inverter_id": "roof", "start": start.isoformat(), "end": end.isoformat(),
                              "quality": quality_status, "complete_coverage": quality_status == "valid",
                              "curtailed": False, "counter_reset": False}]}
    return normalize_capture(raw, quality, normalized_at=received)


@pytest.mark.parametrize("quality_status, expected_pairs", [("valid", 1), ("unknown", 0)])
def test_actual_capture_and_bootstrap_cli_pipeline_remains_insufficient_without_30_days(
        offline_process, tmp_path, quality_status, expected_pairs):
    schedule = tmp_path / "schedule.json"
    schedule.write_text(json.dumps(evaluation_payload()))
    captures = tmp_path / "actuals.jsonl"
    captures.write_text(json.dumps(actual_capture(quality_status=quality_status)) + "\n")
    output = tmp_path / "report.json"
    run = offline_process("evaluate.py", schedule, "--actual-captures", captures, "--output", output,
                          "--bootstrap", "--bootstrap-resamples", "1000", "--bootstrap-seed", "42",
                          "--bootstrap-confidence", "0.95")
    assert run.returncode == 0, run.stderr
    evaluated = json.loads(output.read_text())
    assert evaluated["paired_intervals"] == expected_pairs
    assert evaluated["statistical_acceptance"]["state"] == "insufficient_evidence"
    assert not evaluated["statistical_acceptance"]["accepted"]
    assert evaluated["statistical_acceptance"]["policy_version"] == 1
    assert evaluated["statistical_acceptance"]["seed"] == 42
    if quality_status == "unknown":
        assert evaluated["missing"][0]["missing_actual"]
        assert evaluated["scores"]["adaptive"]["overall"]["mae_w"] is None


def test_actual_capture_cli_rejects_mixed_actuals_and_uses_as_of_cutoff(offline_process, tmp_path):
    payload = evaluation_payload(include_actuals=True)
    first = payload["actuals"][0]
    second = {**first, "start": first["end"],
              "end": "2026-06-21T12:00:00+00:00", "observed_at": "2026-06-21T12:00:00+00:00"}
    payload["actuals"] = [second]
    payload["windows"].append({**payload["windows"][0], "start": second["start"], "end": second["end"]})
    payload["forecasts"].extend([{**row, "start": second["start"], "end": second["end"]}
                                 for row in list(payload["forecasts"])])
    schedule, captures, output = (tmp_path / name for name in ("schedule.json", "actuals.jsonl", "report.json"))
    schedule.write_text(json.dumps(payload))
    captures.write_text(json.dumps(actual_capture()) + "\n")
    run = offline_process("evaluate.py", schedule, "--actual-captures", captures, "--output", output)
    assert run.returncode == 2
    assert "cannot be combined with nonempty input.actuals" in run.stderr
    assert not output.exists()
    payload["as_of"] = "2026-06-21T11:30:00+00:00"
    payload["actuals"] = []
    schedule.write_text(json.dumps(payload))
    run = offline_process("evaluate.py", schedule, "--actual-captures", captures, "--output", output)
    assert run.returncode == 0, run.stderr
    assert json.loads(output.read_text())["paired_intervals"] == 0


@pytest.mark.parametrize("contents", ["\n", '{"schema_version":1}\n', '{"truncated":'])
def test_bad_actual_jsonl_or_schema_never_overwrites_existing_report(offline_process, tmp_path, contents):
    schedule = tmp_path / "schedule.json"
    schedule.write_text(json.dumps(evaluation_payload()))
    archive = tmp_path / "actuals.jsonl"
    archive.write_text(contents)
    output = tmp_path / "existing-report.json"
    output.write_text("preserve existing report\n")
    run = offline_process("evaluate.py", schedule, "--actual-captures", archive, "--output", output)
    assert run.returncode == 2
    assert "Traceback" not in run.stderr
    assert output.read_text() == "preserve existing report\n"


@pytest.mark.parametrize("input_kind", ["schedule", "forecasts", "actuals"])
@pytest.mark.parametrize("alias", ["same_path", "symlink", "hardlink"])
def test_evaluation_output_cannot_overwrite_any_input_alias(offline_process, tmp_path, input_kind, alias):
    schedule, forecasts, actuals = (tmp_path / name for name in ("schedule.json", "forecasts.jsonl", "actuals.jsonl"))
    schedule.write_text("{}")
    forecasts.write_text("forecast archive must stay intact\n")
    actuals.write_text("actual archive must stay intact\n")
    source = {"schedule": schedule, "forecasts": forecasts, "actuals": actuals}[input_kind]
    before = source.read_bytes()
    output = source if alias == "same_path" else tmp_path / "output.json"
    if alias == "symlink":
        output.symlink_to(source)
    elif alias == "hardlink":
        os.link(source, output)
    run = offline_process("evaluate.py", schedule, "--captures", forecasts, "--actual-captures", actuals,
                          "--output", output)
    assert run.returncode == 2
    assert "must not overwrite an input archive" in run.stderr
    assert source.read_bytes() == before


def test_invalid_bootstrap_policy_keeps_existing_output_untouched(offline_process, tmp_path):
    schedule, output = tmp_path / "schedule.json", tmp_path / "output.json"
    schedule.write_text(json.dumps(evaluation_payload(include_actuals=True)))
    output.write_text("existing\n")
    run = offline_process("evaluate.py", schedule, "--output", output, "--bootstrap", "--bootstrap-confidence", "0.9")
    assert run.returncode == 2
    assert output.read_text() == "existing\n"


@pytest.mark.parametrize("name", ["forecast", "evaluate"])
@pytest.mark.parametrize("target", ["script", "component"])
@pytest.mark.parametrize("alias", ["same", "symlink", "hardlink", "after_calculation"])
def test_report_clis_preserve_programs_before_and_after_calculation(tmp_path, monkeypatch, name, target, alias):
    from scripts import evaluate, forecast, replay_paths

    command = forecast if name == "forecast" else evaluate
    root = tmp_path / "project"
    protected = root / (f"scripts/{name}.py" if target == "script" else "custom_components/adaptive_solar/core/models.py")
    protected.parent.mkdir(parents=True)
    protected.write_text("# protected program copy\n")
    monkeypatch.setattr(replay_paths, "SOURCE_ROOT", root)
    source, output = tmp_path / "input.json", tmp_path / "result.json"
    if name == "forecast":
        source.write_bytes((ROOT / "examples/site.json").read_bytes())
        argv = ["forecast.py", "--config", str(source), "--synthetic", "--as-of", "2026-06-21T12:00:00+02:00"]
        calculation = "synthetic_weather"
    else:
        source.write_text(json.dumps(evaluation_payload(include_actuals=True)))
        argv = ["evaluate.py", str(source)]
        calculation = "evaluate_forecasts"
    if alias == "same":
        output = protected
    elif alias == "symlink":
        output.symlink_to(protected)
    elif alias == "hardlink":
        os.link(protected, output)
    if alias == "after_calculation":
        original = getattr(command, calculation)
        def compute_then_alias(*args, **kwargs):
            result = original(*args, **kwargs)
            os.link(protected, output)
            return result
        monkeypatch.setattr(command, calculation, compute_then_alias)
    else:
        monkeypatch.setattr(command, calculation, lambda *args, **kwargs: pytest.fail("aliased output must fail before calculation"))
    monkeypatch.setattr(sys, "argv", [*argv, "--output", str(output)])
    with pytest.raises(SystemExit) as failed:
        command.main()
    assert failed.value.code == 2
    assert protected.read_text() == "# protected program copy\n"


@pytest.mark.parametrize("name", ["forecast", "evaluate"])
def test_report_clis_atomically_replace_an_unrelated_report_hardlink(tmp_path, monkeypatch, name):
    from scripts import evaluate, forecast

    previous, output, source = (tmp_path / n for n in ("previous.json", "output.json", "input.json"))
    previous.write_text("old report copy\n")
    os.link(previous, output)
    if name == "forecast":
        source.write_bytes((ROOT / "examples/site.json").read_bytes())
        argv = ["forecast.py", "--config", str(source), "--synthetic", "--as-of", "2026-06-21T12:00:00+02:00"]
        command = forecast
    else:
        source.write_text(json.dumps(evaluation_payload(include_actuals=True)))
        argv = ["evaluate.py", str(source)]
        command = evaluate
    monkeypatch.setattr(sys, "argv", [*argv, "--output", str(output)])
    command.main()
    assert isinstance(json.loads(output.read_text()), dict)
    assert previous.read_text() == "old report copy\n"
