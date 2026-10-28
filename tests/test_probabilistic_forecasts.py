"""Complete member windows, coherent stage sums and causal probability scores."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.adaptive_solar.core.models import ForecastPoint, ForecastResult
from custom_components.adaptive_solar.core.probability import (
    CalibrationCase, EnergyDistribution, calibrate_bias, combine_families, probability_scores, window_distribution,
)

NOW = datetime(2026, 6, 20, tzinfo=UTC)


def distribution(family="icon", product="d2", count=2):
    return EnergyDistribution(family, product, NOW, NOW + timedelta(hours=24), tuple(range(count)),
                              (1 / count,) * count, tuple(str(index) for index in range(count)), count)


def test_shared_stages_are_aggregated_within_same_member_before_quantiles():
    results = {}
    for member, powers in (("m0", (100, 1900)), ("m1", (1900, 100))):
        points = tuple(ForecastPoint(NOW, NOW + timedelta(hours=1), stage, power, power)
                       for stage, power in zip(("a", "b"), powers, strict=True))
        results[member] = ForecastResult(NOW, points)
    output = window_distribution("d2", "icon", results, NOW, NOW + timedelta(hours=1), 2, ("a", "b"))
    assert output.values_kwh == (2, 2)
    assert output.quantile(.1) == 2
    broken = replace(results["m1"], points=results["m1"].points[:1])
    with pytest.raises(ValueError, match="cohort"):
        window_distribution("d2", "icon", {**results, "m1": broken}, NOW, NOW + timedelta(hours=1), 2, ("a", "b"))
    partial = window_distribution("d2", "icon", {**results, "m1": broken}, NOW, NOW + timedelta(hours=1),
                                  2, ("a", "b"), quorum=.5)
    assert partial.values_kwh == (2,) and partial.excluded_members == ("m1",)
    assert partial.expected_members == 2 and "incomplete" in partial.status


def test_different_family_member_counts_do_not_determine_family_weights():
    icon, ifs = distribution(count=20), distribution("ifs", "europe", count=51)
    mixed = combine_families((icon, ifs))
    assert sum(mixed.weights[:20]) == pytest.approx(.5)
    assert sum(mixed.weights[20:]) == pytest.approx(.5)
    with pytest.raises(ValueError, match="one product per family"):
        combine_families((ifs, distribution("ifs", "025", 51)))
    with pytest.raises(ValueError, match="windows"):
        combine_families((icon, replace(ifs, end=NOW + timedelta(hours=48))))


@pytest.mark.parametrize("month,day,hours", [(3, 29, 23), (10, 25, 25)])
def test_member_windows_integrate_both_dst_days_without_24_hour_assumption(month, day, hours):
    local = datetime(2026, month, day, tzinfo=ZoneInfo("Europe/Berlin"))
    start, end = local.astimezone(UTC), (local + timedelta(days=1)).astimezone(UTC)
    result = ForecastResult(start, tuple(ForecastPoint(start + timedelta(hours=index), start + timedelta(hours=index + 1),
                                                       "a", 1000, 1000) for index in range(hours)))
    output = window_distribution("eps", "icon", {"m": result}, start, end, 1, ("a",))
    assert output.quantile(.5) == hours


def test_empirical_scores_have_known_values_and_threshold_is_strictly_below():
    output = replace(distribution(), values_kwh=(0, 2))
    scores = probability_scores(output, 1, (1, 2))
    assert scores["crps_kwh"] == pytest.approx(.5)
    assert scores["quantile_loss_kwh"] == {"0.1": .1, "0.5": .5, "0.9": pytest.approx(.1)}
    assert scores["brier"]["1"] == .25
    assert output.probability_below(2) == .5
    assert scores["coverage_80"] is True


def cases(count=21):
    result = []
    for index in range(count):
        start = NOW - timedelta(days=index + 2)
        result.append(CalibrationCase(start, start, start + timedelta(days=1), start + timedelta(days=1, hours=1),
                                      3, 4, "icon", "d2"))
    return tuple(result)


def test_chronological_calibration_excludes_future_labels_and_wrong_strata():
    prior = cases(20)
    contaminated = (*prior, replace(prior[0], available_at=NOW + timedelta(seconds=1), actual_kwh=1e6),
                    replace(prior[0], family="ifs", actual_kwh=1e6),
                    replace(prior[0], issued_at=prior[0].target_start + timedelta(hours=1), actual_kwh=1e6))
    output = calibrate_bias(distribution(), contaminated, NOW)
    assert output.values_kwh == (1, 2)
    assert "spread_unvalidated" in output.status and output.calibration_sha256
    clean = calibrate_bias(distribution(), tuple(reversed(prior)), NOW)
    assert clean.calibration_sha256 == output.calibration_sha256
    with pytest.raises(ValueError, match="insufficient"):
        calibrate_bias(distribution(), cases(19), NOW)
    with pytest.raises(ValueError, match="duplicate"):
        calibrate_bias(distribution(), (*prior, prior[0]), NOW)
    with pytest.raises(ValueError, match="cutoff"):
        calibrate_bias(distribution(), prior, NOW + timedelta(seconds=1))


def test_raw_spread_is_never_presented_as_calibrated():
    assert distribution().summary((1,))["status"] == "raw_ensemble_uncalibrated"
    with pytest.raises(ValueError):
        EnergyDistribution("x", "y", NOW, NOW + timedelta(hours=1), (True,), (1,), ("m",), 1)
