"""Conditional bootstrap mechanics on synthetic archives, not accuracy proof."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from custom_components.adaptive_solar.core.evaluation import (
    ActualRecord, EvaluationWindow, ForecastRecord, evaluate_forecasts,
)
from custom_components.adaptive_solar.core.statistical_validation import paired_day_bootstrap

EPOCH = datetime(2025, 1, 1, tzinfo=timezone.utc)


def report(days=40, *, inverters=("a",), horizons=("day_1_at_06:00",), candidate_error=None,
           reference_error=None):
    candidate_error = candidate_error or (lambda day, inverter, horizon: 0.2 + 0.03 * (day % 4))
    reference_error = reference_error or (lambda day, inverter, horizon, reference: 1.0 + 0.1 * (day % 3))
    result = {"sources": ["adaptive", "helios", "open_meteo"],
              "policy": {"min_paired_days": 30, "min_relative_improvement": 0.05},
              "comparison_eligible": True,
              "supports_improvement_over_both_references_on_paired_archive": True,
              "strata": {}, "energy_pairs": []}
    for inverter in inverters:
        for horizon in horizons:
            name = f"{inverter}|{horizon}"
            expected = []
            for index in range(days):
                target = EPOCH + timedelta(days=index)
                cutoff = target - timedelta(hours=18)
                key = {"target_day": target.date().isoformat(), "cutoff": cutoff.isoformat()}
                expected.append(key)
                result["energy_pairs"].append({**key, "inverter_id": inverter, "horizon": horizon,
                    "actual_kwh": 10.0, "kind": "day",
                    "forecasts_kwh": {"adaptive": 10 + candidate_error(index, inverter, horizon),
                                      **{reference: 10 + reference_error(index, inverter, horizon, reference)
                                         for reference in ("helios", "open_meteo")}}})
            result["strata"][name] = {"inverter_id": inverter, "horizon": horizon, "expected_pairs": expected}
    return result


def bootstrap(payload, **kwargs):
    return paired_day_bootstrap(payload, n_resamples=1000, **kwargs)


def test_clear_paired_win_all_strata_and_both_references_passes_conditionally():
    payload = report(inverters=("a", "b"), horizons=("day_1_at_06:00", "day_2_at_06:00"))
    original = deepcopy(payload)
    result = bootstrap(payload)
    assert result["state"] == "accepted_conditional"
    assert result["accepted"]
    assert result["family_size"] == 4 * 2 * 2
    assert result["resamples"] > result["requested_resamples"]
    assert result["joint_target_day_count"] == 40
    assert result["individual_interval_confidence_level"] == pytest.approx(1 - 0.05 / 16)
    for stratum in result["strata"].values():
        for comparison in stratum["comparisons"].values():
            assert comparison["mae_difference_kwh"] < 0
            assert comparison["mae_difference_ci_kwh"][1] < 0
            assert comparison["relative_skill_ci"][0] > 0.05
            assert comparison["accepted"]
    assert payload == original
    json.dumps(result, allow_nan=False)


def test_noisy_favorable_point_estimate_is_not_statistical_evidence():
    payload = report(candidate_error=lambda day, inverter, horizon: 0.5 if day % 2 == 0 else 1.38,
                     reference_error=lambda *args: 1.0)
    result = bootstrap(payload)
    comparison = result["strata"]["a|day_1_at_06:00"]["comparisons"]["helios"]
    assert comparison["relative_skill"] > 0.05
    assert comparison["relative_skill_ci"][0] < 0.05
    assert comparison["mae_difference_ci_kwh"][1] > 0
    assert not result["accepted"]


def test_bias_and_bad_inverter_cannot_hide_behind_favorable_aggregate():
    payload = report(inverters=("good", "bad"),
                     candidate_error=lambda day, inverter, horizon: 0.05 if inverter == "good" else 1.1,
                     reference_error=lambda *args: 1.0)
    result = bootstrap(payload)
    assert not result["accepted"]
    assert result["strata"]["good|day_1_at_06:00"]["comparisons"]["helios"]["accepted"]
    assert not result["strata"]["bad|day_1_at_06:00"]["comparisons"]["helios"]["accepted"]
    # Lower MAE alone cannot hide worse absolute signed energy bias.
    payload = report(candidate_error=lambda *args: 0.1,
                     reference_error=lambda day, *args: -1 if day % 2 else 1)
    result = bootstrap(payload)
    comparison = result["strata"]["a|day_1_at_06:00"]["comparisons"]["helios"]
    assert comparison["relative_skill_ci"][0] > 0.05
    assert not comparison["absolute_bias_not_increased"]
    assert not result["accepted"]


def test_missing_expected_stratum_or_reference_never_borrows_evidence():
    payload = report(inverters=("a", "b"))
    payload["energy_pairs"] = [row for row in payload["energy_pairs"] if row["inverter_id"] == "a"]
    result = bootstrap(payload)
    assert result["family_size"] == 8
    assert not result["accepted"]
    assert result["strata"]["b|day_1_at_06:00"]["complete_target_days"] == 0
    assert result["joint_target_day_count"] == 0
    payload = report(days=30)
    del payload["energy_pairs"][0]["forecasts_kwh"]["open_meteo"]
    result = bootstrap(payload)
    assert result["joint_target_day_count"] == 29
    assert not result["accepted"]


def replicate_issues(payload, count):
    original = deepcopy(payload)
    payload["energy_pairs"] = []
    for stratum in payload["strata"].values():
        stratum["expected_pairs"] = []
    for row in original["energy_pairs"]:
        for index in range(count):
            cutoff = (datetime.fromisoformat(row["cutoff"]) + timedelta(seconds=index)).isoformat()
            payload["energy_pairs"].append({**deepcopy(row), "cutoff": cutoff})
            payload["strata"][f"{row['inverter_id']}|{row['horizon']}"]["expected_pairs"].append(
                {"cutoff": cutoff, "target_day": row["target_day"]})


def test_within_day_issue_repetition_does_not_create_independent_observations():
    payload = report(candidate_error=lambda day, *args: 0.4 if day % 2 else 1.2,
                     reference_error=lambda *args: 1.0)
    original = bootstrap(payload)
    replicate_issues(payload, 20)
    repeated = bootstrap(payload)
    assert repeated["joint_target_day_count"] == original["joint_target_day_count"] == 40
    first = original["strata"]["a|day_1_at_06:00"]["comparisons"]["helios"]
    second = repeated["strata"]["a|day_1_at_06:00"]["comparisons"]["helios"]
    assert second["relative_skill_ci"] == pytest.approx(first["relative_skill_ci"])
    assert second["mae_difference_ci_kwh"] == pytest.approx(first["mae_difference_ci_kwh"])
    # Even 600 issue rows from 29 days cannot satisfy a 30-day minimum.
    payload = report(days=29)
    replicate_issues(payload, 20)
    assert not bootstrap(payload)["accepted"]


def test_missing_one_expected_issue_invalidates_its_entire_day_block():
    payload = report(days=30)
    replicate_issues(payload, 3)
    payload["energy_pairs"].pop()
    result = bootstrap(payload)
    assert result["joint_target_day_count"] == 29
    assert result["strata"]["a|day_1_at_06:00"]["missing_or_invalid_target_days"] == ["2025-01-30"]
    assert not result["accepted"]


def test_conflicting_duplicate_or_nonfinite_pair_is_missing_not_selected():
    payload = report(days=30)
    bad = deepcopy(payload["energy_pairs"][0])
    bad["forecasts_kwh"]["adaptive"] = 10
    payload["energy_pairs"].append(bad)
    assert bootstrap(payload)["joint_target_day_count"] == 29
    payload = report(days=30)
    payload["energy_pairs"][0]["actual_kwh"] = float("nan")
    result = bootstrap(payload)
    assert result["joint_target_day_count"] == 29
    json.dumps(result, allow_nan=False)


def test_zero_reference_and_undefined_skill_resamples_stay_json_safe():
    payload = report(candidate_error=lambda *args: 0, reference_error=lambda *args: 0)
    result = bootstrap(payload)
    comparison = result["strata"]["a|day_1_at_06:00"]["comparisons"]["helios"]
    assert comparison["relative_skill"] is None
    assert comparison["relative_skill_ci"] is None
    assert comparison["undefined_skill_resamples"] == result["resamples"]
    assert not result["accepted"]
    json.dumps(result, allow_nan=False)


def test_descriptive_gate_is_required_even_with_clear_statistical_win():
    payload = report()
    payload["comparison_eligible"] = False
    result = bootstrap(payload)
    assert not result["accepted"]
    assert "descriptive_gate_not_passed" in result["gate_reasons"]


@pytest.mark.parametrize("scope", ["inverter", "horizon"])
def test_bootstrap_cannot_accept_mean_skill_when_a_stratum_loses_most_days(scope):
    from tests.test_evaluation import daily_win_masking_report

    payload = daily_win_masking_report(scope)
    result = bootstrap(payload)
    assert result["joint_target_day_count"] == 40
    # Mean skill, bias and simultaneous CIs all support this synthetic mean
    # improvement, yet the separate daily-win requirement must still reject it.
    assert all(comparison["accepted"] for stratum in result["strata"].values()
               for comparison in stratum["comparisons"].values())
    assert not result["descriptive_gate_passed"]
    assert result["gate_reasons"] == ["descriptive_gate_not_passed"]
    assert result["state"] == "not_supported"
    assert not result["accepted"]


def test_reproducible_seed_and_shared_inverter_day_draws():
    payload = report(inverters=("a", "b"))
    first, second = bootstrap(payload, seed=7), bootstrap(payload, seed=7)
    assert first == second
    a = first["strata"]["a|day_1_at_06:00"]["comparisons"]["helios"]
    b = first["strata"]["b|day_1_at_06:00"]["comparisons"]["helios"]
    assert a["relative_skill_ci"] == b["relative_skill_ci"]
    assert a["mae_difference_ci_kwh"] == b["mae_difference_ci_kwh"]


@pytest.mark.parametrize("start_date, expected_short_or_long_day", [("2025-03-15", 23), ("2025-10-10", 25)])
def test_real_evaluation_day_blocks_preserve_dst_energy_and_schedule(start_date, expected_short_or_long_day):
    zone = ZoneInfo("Europe/Berlin")
    epoch = datetime.fromisoformat(start_date)
    forecasts, actuals, windows = [], [], []
    for index in range(32):
        start = (epoch + timedelta(days=index)).replace(tzinfo=zone).astimezone(timezone.utc)
        end = (epoch + timedelta(days=index + 1)).replace(tzinfo=zone).astimezone(timezone.utc)
        cutoff = start - timedelta(hours=6)
        windows.append(EvaluationWindow(cutoff, start, end, "a"))
        actuals.append(ActualRecord(start, end, "a", 1000, end))
        for source, power in (("adaptive", 1100), ("helios", 1500), ("open_meteo", 1400)):
            forecasts.append(ForecastRecord(source, cutoff, start, end, "a", power))
    evaluated = evaluate_forecasts(forecasts, actuals, windows, as_of=datetime(2026, 1, 1, tzinfo=timezone.utc),
                                   timezone_name="Europe/Berlin", sources=("adaptive", "helios", "open_meteo"),
                                   min_paired_intervals=1)
    assert expected_short_or_long_day in [pair["actual_kwh"] for pair in evaluated["energy_pairs"]]
    result = bootstrap(evaluated)
    assert result["joint_target_day_count"] == 32
    assert result["accepted"]


@pytest.mark.parametrize("kwargs", [{"min_paired_days": 29}, {"references": ("helios",)},
                                    {"confidence_level": 0.9}, {"seed": -1}, {"n_resamples": True}])
def test_invalid_or_weakened_predeclared_bootstrap_policy_rejected(kwargs):
    with pytest.raises(ValueError):
        paired_day_bootstrap(report(), **kwargs)


def test_bonferroni_family_includes_all_declared_metrics_even_without_data():
    payload = report(inverters=("a", "b"), horizons=("day_1_at_06:00", "rest_of_day_12:00"))
    payload["energy_pairs"] = []
    result = bootstrap(payload)
    assert result["family_size"] == 16
    assert result["endpoint_tail_probability"] == pytest.approx(0.05 / (2 * 16))
    assert not result["accepted"]


def test_samples_are_drawn_by_day_not_elapsed_hours(monkeypatch):
    # Inspect the RNG request: every replicate draws exactly the 40 target-day
    # indices; inverter/issue counts cannot enlarge the resampling dimension.
    payload = report(inverters=("a", "b"))
    real_rng = np.random.default_rng(20261024)
    shapes = []

    class RecordingRng:
        def integers(self, low, high, size):
            shapes.append((high, size))
            return real_rng.integers(low, high, size=size)

    monkeypatch.setattr(np.random, "Generator", lambda bit_generator: RecordingRng())
    bootstrap(payload)
    assert shapes and all(high == 40 and size[1] == 40 for high, size in shapes)


def test_extreme_confidence_is_rejected_before_unbounded_allocation():
    with pytest.raises(ValueError, match="bounded offline computation"):
        bootstrap(report(), confidence_level=0.999999999)
