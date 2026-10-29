"""Reconstruct issued inputs/state, verify baseline and real EPS end to end."""
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json

import pytest

from custom_components.adaptive_solar.archive_export import json_value, replay_events, software_provenance
from custom_components.adaptive_solar.core.archive import ArchiveJournal, ArchiveStore
from custom_components.adaptive_solar.core.engine import ForecastEngine
from custom_components.adaptive_solar.core.learning import ResidualLearner
from custom_components.adaptive_solar.core.models import InverterConfig, SiteConfig, StringConfig
from custom_components.adaptive_solar.core.replay import Candidate, reconstruct_state, replay_forecast
from custom_components.adaptive_solar.weather import parse_forecast
from scripts.capture_weather import archive_response, flush_journal
from scripts.replay_archive import main, weather_probabilities
from tests.test_ensemble_archive import eps_payload
from tests.test_weather import payload as deterministic_payload

NOW = datetime(2026, 6, 1, 10, tzinfo=UTC)


def site():
    return SiteConfig(52.52, 13.41, "Europe/Berlin", (StringConfig("s", "i", 5, 30, 180),),
                      (InverterConfig("i", 5),), weather_models=("best_match",))


def forecast_bundle(tmp_path, *, observation=False):
    config = site()
    raw = deterministic_payload(count=4)
    weather = parse_forecast(raw, "best_match", NOW, config)
    journal = ArchiveJournal(tmp_path / "journal")
    original = journal.append("weather_response", {"model": "best_match", "status": "available", "raw_response": raw}, NOW)
    observations = []
    if observation:
        observations = [{"time": NOW.isoformat(), "inverter_id": "i", "power_w": 2000}]
    from custom_components.adaptive_solar.core.models import Observation

    parsed_obs = tuple(Observation(**{**row, "time": NOW}) for row in observations)
    learner = ResidualLearner(timezone_name=config.timezone, output_caps={"i": 5000}).fit([], NOW)
    result = ForecastEngine(config).forecast((weather,), NOW, parsed_obs, learner)
    payload = {"site": config.to_dict(), "weather": json_value((weather,)), "observations": observations,
               "issued_at": NOW.isoformat(), "result": json_value(result), "software": software_provenance(),
               "weather_receipt_ids": {"best_match": original["event_id"]}}
    state = {"fit_as_of": NOW.isoformat(), "fit_samples": [], "learner_available": True, "shading": {"schema": 3, "inverters": {}, "released": {}}, "history_revision": 1}
    events = replay_events(payload, state, NOW + timedelta(seconds=1))
    for kind, value, received, event_id in events:
        journal.append(kind, json.loads(value), received, event_id)
    rows = journal.page(limit=100)["events"]
    return rows[-1], rows, state


@pytest.mark.parametrize("observation", [False, True])
def test_exact_forecast_baseline_reconstructs_observations_state_and_numerics(tmp_path, observation):
    event, rows, _ = forecast_bundle(tmp_path, observation=observation)
    report = replay_forecast(event, rows)
    assert report["baseline"]["matched"]
    assert report["baseline"]["max_error_w"] == 0
    assert report["baseline"]["accepted"]
    assert report["input_sha256"]


def test_ha_removal_does_not_forge_historical_environment_acceptance(tmp_path, monkeypatch):
    from custom_components.adaptive_solar import archive_export

    event, rows, _ = forecast_bundle(tmp_path)
    archived = event["payload"]["software"]
    assert archived["libraries"]["homeassistant"] is not None
    actual = {**archived, "libraries": {**archived["libraries"], "homeassistant": None}}
    monkeypatch.setattr(archive_export, "software_provenance", lambda: actual)
    report = replay_forecast(event, rows)
    assert report["baseline"]["matched"]
    assert not report["baseline"]["software_match"]
    assert not report["baseline"]["accepted"]
    assert event["payload"]["software"] == archived


def test_replay_refuses_missing_or_cross_source_state_and_asof_before_receipt(tmp_path):
    event, rows, _ = forecast_bundle(tmp_path)
    with pytest.raises(ValueError, match="missing"):
        replay_forecast(event, [event])
    cross = deepcopy(rows)
    cross[0]["source"] = "other_ha"
    with pytest.raises(ValueError, match="missing"):
        replay_forecast(event, cross)
    with pytest.raises(ValueError, match="as-of"):
        replay_forecast(event, rows, as_of=NOW)


def test_replay_state_checksum_or_decompression_bound_cannot_be_bypassed(tmp_path):
    event, rows, expected = forecast_bundle(tmp_path)
    assert reconstruct_state(event, rows) == expected
    changed = deepcopy(rows)
    chunk = next(event["payload"] for event in changed if event["kind"] == "forecast_state_chunk")
    if "data_fragment" in chunk:
        chunk["data_fragment"] = "YWJjZA=="
    else:
        chunk["json_fragment"] += "x"
    with pytest.raises(ValueError):
        reconstruct_state(event, changed)
    changed_event = deepcopy(event)
    changed_event["payload"]["replay_state"]["encoding"] = "unknown-codec"
    with pytest.raises(ValueError):
        reconstruct_state(changed_event, rows)


def test_changed_software_fails_acceptance_even_with_matching_power(tmp_path):
    event, rows, _ = forecast_bundle(tmp_path)
    event["payload"]["software"]["source_sha256"] = "0" * 64
    report = replay_forecast(event, rows)
    assert report["baseline"]["matched"] and not report["baseline"]["accepted"]


def test_candidate_inputs_are_independent_and_explicitly_versioned(tmp_path):
    event, rows, _ = forecast_bundle(tmp_path)

    def mutated(inputs):
        inputs.learner.status["test"] = {"changed": True}
        return ForecastEngine(inputs.site).forecast(inputs.weather, inputs.issued_at)

    def clean(inputs):
        assert "test" not in inputs.learner.status
        return ForecastEngine(inputs.site).forecast(inputs.weather, inputs.issued_at)

    report = replay_forecast(event, rows, candidates=(Candidate("a", "experiment1", mutated), Candidate("b", "experiment2", clean)))
    assert report["candidate_versions"]["b"] == "experiment2"
    with pytest.raises(ValueError, match="unique"):
        replay_forecast(event, rows, candidates=(Candidate("baseline", "x", clean),))


def test_future_weather_receipt_is_rejected_instead_of_relabelled(tmp_path):
    event, rows, _ = forecast_bundle(tmp_path)
    event["payload"]["weather"][0]["issued_at"] = (NOW + timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError, match="disagrees"):
        replay_forecast(event, rows)


def test_original_weather_receipt_is_required_and_must_reproduce_used_cells(tmp_path):
    event, rows, _ = forecast_bundle(tmp_path)
    without_original = [row for row in rows if row["kind"] != "weather_response"]
    with pytest.raises(ValueError, match="missing.*weather receipt"):
        replay_forecast(event, without_original)
    changed = deepcopy(rows)
    original = next(row for row in changed if row["kind"] == "weather_response")
    original["payload"]["raw_response"]["hourly"]["shortwave_radiation"][1] += 10
    with pytest.raises(ValueError, match="differs"):
        replay_forecast(event, changed)
    original["generation"] = "other-generation"
    with pytest.raises(ValueError, match="missing.*weather receipt"):
        replay_forecast(event, changed)


def test_host_eps_replays_per_member_physics_full_cohort_and_raw_scores(tmp_path):
    journal = ArchiveJournal(tmp_path / "journal")
    manifests = []
    for product in ("dwd_icon_d2_eps", "ecmwf_ifs_europe_ensemble", "ecmwf_ifs025_ensemble"):
        manifests.append(archive_response(journal, {}, json.dumps(eps_payload(product)).encode(), NOW,
                                         product=product, ensemble=True, http_status=200))
    rows = journal.page(limit=100)["events"]
    report = weather_probabilities(manifests, rows, site(), NOW, NOW, NOW + timedelta(hours=2),
                                   thresholds=(2, 5), actual_kwh=4)
    assert report["status"] == "raw_probabilities"
    assert report["diagnostics"]["ifs"]["selected_product"] == "ecmwf_ifs_europe_ensemble"
    d2 = report["distributions"]["dwd_icon_d2_eps"]
    assert d2["member_count"] == 20 and d2["expected_members"] == 20
    assert d2["q10_kwh"] <= d2["q50_kwh"] <= d2["q90_kwh"]
    assert "scores" in d2 and "uncalibrated" in d2["status"]
    mixture = report["distributions"]["family_mixture"]
    assert mixture["member_count"] == 71
    assert sum(value for key, value in mixture["weights"].items() if key.startswith("dwd_icon")) == pytest.approx(.5)


def test_host_short_model_never_stitches_to_ifs_and_failed_latest_invalidates(tmp_path):
    journal = ArchiveJournal(tmp_path / "journal")
    manifests = []
    for product, count in (("dwd_icon_d2_eps", 2), ("ecmwf_ifs_europe_ensemble", 4), ("ecmwf_ifs025_ensemble", 4)):
        manifests.append(archive_response(journal, {}, json.dumps(eps_payload(product, count)).encode(), NOW,
                                         product=product, ensemble=True, http_status=200))
    manifests.append(archive_response(journal, {}, b"failure", NOW + timedelta(seconds=1),
                                     product="ecmwf_ifs_europe_ensemble", ensemble=True, http_status=503))
    rows = journal.page(limit=100)["events"]
    report = weather_probabilities(manifests, rows, site(), NOW + timedelta(seconds=1), NOW + timedelta(seconds=1),
                                   NOW + timedelta(hours=2))
    assert report["diagnostics"]["dwd_icon_d2_eps"]["status"] == "unavailable"
    assert report["diagnostics"]["ifs"]["selected_product"] == "ecmwf_ifs025_ensemble"
    assert "family_mixture" not in report["distributions"]


def test_cli_replays_immutable_dataset_without_network(tmp_path, monkeypatch):
    event, rows, _ = forecast_bundle(tmp_path)
    journal, store = ArchiveJournal(tmp_path / "journal"), ArchiveStore(tmp_path / "store")
    flush_journal(journal, store, "ha:test")
    store.pin("frozen1")
    output = tmp_path / "report.json"
    monkeypatch.setattr("sys.argv", ["replay_archive.py", "--archive", str(tmp_path / "store"), "--source", "ha:test",
                                     "--dataset", "frozen1", "--output", str(output), "--physics-ablation"])
    assert main() == 0
    report = json.loads(output.read_text())
    assert report["event_id"] == event["event_id"] and report["selected_envelopes_sha256"]
    assert report["dataset"] == "frozen1" and "physics_ablation" in report["outputs"]


def test_active_cached_learner_rebuilds_from_compressed_original_fit_samples(tmp_path):
    from tests.test_learning import synthetic_days

    config = site()
    shift = timedelta(days=372)
    samples = [replace(row, issued_at=row.issued_at + shift, start=row.start + shift,
                       end=row.end + shift, observed_at=row.observed_at + shift, inverter_id="i")
               for row in synthetic_days()]
    samples = [replace(row, measurement_support=((row.start, row.end),)) for row in samples]
    fit_cutoff = max(row.observed_at for row in samples) + timedelta(minutes=1)
    learner = ResidualLearner(timezone_name=config.timezone, output_caps={"i": 5000}).fit(samples, fit_cutoff)
    assert learner.status["i"]["state"] == "active"
    raw = deterministic_payload(count=10)
    raw["hourly"]["shortwave_radiation"] = [300] * 10
    raw["hourly"]["direct_normal_irradiance"] = [400] * 10
    weather = parse_forecast(raw, "best_match", NOW, config)
    result = ForecastEngine(config).forecast((weather,), NOW, learner=learner)
    assert any(point.power_w != point.baseline_w for point in result.points)
    journal = ArchiveJournal(tmp_path / "journal")
    original = journal.append("weather_response", {"model": "best_match", "status": "available", "raw_response": raw}, NOW)
    payload = {"site": config.to_dict(), "weather": json_value((weather,)), "observations": [],
               "issued_at": NOW.isoformat(), "result": json_value(result), "software": software_provenance(),
               "weather_receipt_ids": {"best_match": original["event_id"]}}
    state = {"fit_as_of": fit_cutoff.isoformat(), "fit_samples": json_value(samples),
             "shading": {"schema": 3, "inverters": {}, "released": {}}, "history_revision": 1}
    for kind, value, received, event_id in replay_events(payload, state, NOW + timedelta(seconds=1)):
        journal.append(kind, json.loads(value), received, event_id)
    rows = journal.page(limit=100)["events"]
    assert rows[-1]["payload"]["replay_state"]["encoding"] == "zlib+base64"
    report = replay_forecast(rows[-1], rows)
    assert report["baseline"]["accepted"] and report["baseline"]["max_error_w"] == 0


@pytest.mark.parametrize("changed", ["features", "model_status", "member_power", "member_issue"])
def test_baseline_acceptance_includes_features_status_and_individual_model_outputs(tmp_path, changed):
    event, rows, _ = forecast_bundle(tmp_path)
    result = event["payload"]["result"]
    if changed == "features":
        result["points"][0]["features"]["beam_shade_factor"] = .5
    elif changed == "model_status":
        result["model_status"]["i"] = "different"
    elif changed == "member_power":
        result["member_points"]["best_match"][0]["power_w"] += 1
    else:
        result["member_issued_at"]["best_match"] = (NOW - timedelta(seconds=1)).isoformat()
    report = replay_forecast(event, rows)
    assert not report["baseline"]["matched"]
    assert not report["baseline"]["accepted"]
