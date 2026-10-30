"""Fair pairing, missingness, cutoff and DST behavior of archive comparison."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from zoneinfo import ZoneInfo

import pytest

from custom_components.adaptive_solar.core.evaluation import (
    ActualRecord, EvaluationWindow, ForecastAttempt, ForecastRecord, evaluate_forecasts,
)

EPOCH = datetime(2025, 4, 1, tzinfo=timezone.utc)
SOURCES = ("adaptive", "physics", "helios", "open_meteo")


def archive(days=32):
    forecasts, actuals, windows = [], [], []
    for day in range(days):
        cutoff = EPOCH + timedelta(days=day)
        for hour in range(24):
            start = cutoff + timedelta(hours=hour)
            end = start + timedelta(hours=1)
            actual = 500 if 6 <= hour < 18 else 0
            windows.append(EvaluationWindow(cutoff, start, end, "wr"))
            actuals.append(ActualRecord(start, end, "wr", actual, end + timedelta(minutes=1)))
            for source, error in (("adaptive", 10), ("physics", 80), ("helios", 60), ("open_meteo", 100)):
                forecasts.append(ForecastRecord(source, cutoff, start, end, "wr", actual + error if actual else 0))
    return forecasts, actuals, windows


def evaluate(forecasts, actuals, windows, **kwargs):
    return evaluate_forecasts(forecasts, actuals, windows, as_of=EPOCH + timedelta(days=400), **kwargs)


def daily_win_masking_report(scope, *, wins_per_five=2):
    """Large daily wins mask a smaller stratum's mostly losing days pre-fix."""
    forecasts, actuals, windows = [], [], []
    for day in range(40):
        midnight = EPOCH + timedelta(days=day)
        end = midnight + timedelta(days=1)
        if scope == "inverter":
            groups = [("large", midnight - timedelta(days=1), midnight, end, 1.0, 10.0),
                      ("small", midnight - timedelta(days=1), midnight, end,
                       0.0 if day % 5 < wins_per_five else 1.01, 1.0)]
            for inverter in ("large", "small"):
                actuals.append(ActualRecord(midnight, end, inverter, 1000, end))
        else:
            noon = midnight + timedelta(hours=12)
            groups = [("wr", midnight - timedelta(days=1), midnight, end, 1.0, 10.0),
                      ("wr", noon, noon, end, 0.0 if day % 5 < wins_per_five else 1.01, 1.0)]
            # Actuals remain whole measured intervals for both day/rest windows.
            actuals.extend([ActualRecord(midnight, noon, "wr", 1000, noon),
                            ActualRecord(noon, end, "wr", 1000, end)])
        for inverter, cutoff, start, stop, adaptive_error, reference_error in groups:
            windows.append(EvaluationWindow(cutoff, start, stop, inverter))
            hours = (stop - start).total_seconds() / 3600
            for source in ("adaptive", "helios", "open_meteo"):
                error = adaptive_error if source == "adaptive" else reference_error
                forecasts.append(ForecastRecord(source, cutoff, start, stop, inverter, 1000 + error * 1000 / hours))
    return evaluate(forecasts, actuals, windows, sources=("adaptive", "helios", "open_meteo"),
                    min_paired_intervals=1)


@pytest.mark.parametrize("scope", ["inverter", "horizon"])
def test_daily_win_gate_is_required_for_each_declared_inverter_horizon(scope):
    report = daily_win_masking_report(scope)
    bad = "small|day_1_at_00:00" if scope == "inverter" else "wr|rest_of_day_12:00"
    good = "large|day_1_at_00:00" if scope == "inverter" else "wr|day_1_at_00:00"
    assert report["comparison_eligible"]
    assert report["scores"]["adaptive"]["overall"]["mae_w"] < report["scores"]["helios"]["overall"]["mae_w"]
    for source in ("helios", "open_meteo"):
        improvement = report["improvement"][source]
        # All the other performance checks pass. Only the small stratum's
        # 16/40 daily wins must veto the improvement claim.
        for gate in ("by_horizon", "by_inverter_horizon", "by_inverter_lead"):
            assert all(improvement[gate].values())
        checks = improvement["daily_win_by_inverter_horizon"]
        assert set(checks) == set(report["strata"])
        assert checks[good]["daily_win_fraction"] == 1
        assert checks[good]["passed"]
        assert checks[bad]["paired_target_days"] == 40
        assert checks[bad]["winning_target_days"] == 16
        assert checks[bad]["daily_win_fraction"] == pytest.approx(0.4)
        assert not checks[bad]["passed"]
        assert checks[bad]["gate_reasons"] == ["insufficient_daily_win_fraction"]
        assert improvement["daily_win_fraction"] == pytest.approx(0.4)
        assert improvement["daily_win_fraction_summary"] == "minimum_across_declared_inverter_horizon_strata"
        assert f"insufficient_daily_win_fraction:{bad}" in improvement["daily_win_gate_reasons"]
        assert not improvement["supports_improvement_on_paired_archive"]
    assert not report["supports_improvement_over_both_references_on_paired_archive"]
    json.dumps(report, allow_nan=False)


def test_daily_win_gate_accepts_its_unchanged_threshold_in_every_stratum():
    report = daily_win_masking_report("horizon", wins_per_five=3)
    assert report["policy"]["min_daily_win_fraction"] == 0.6
    assert report["supports_improvement_over_both_references_on_paired_archive"]
    assert report["improvement"]["helios"]["daily_win_fraction"] == pytest.approx(0.6)


def test_daily_win_counts_complete_days_once_even_with_multiple_declared_origins():
    forecasts, actuals, windows = archive()
    first_windows = [replace(row, cutoff=row.cutoff - timedelta(days=1)) for row in windows]
    second_windows = [replace(row, cutoff=row.cutoff - timedelta(days=1) + timedelta(seconds=30)) for row in windows]
    first_forecasts = [replace(row, issued_at=row.issued_at - timedelta(days=1)) for row in forecasts]
    second_forecasts = [replace(row, issued_at=row.issued_at - timedelta(days=1) + timedelta(seconds=30)) for row in forecasts]
    # One incomplete planned origin removes that day from the win denominator;
    # its other complete origin cannot be selected as a representative winner.
    second_forecasts = [replace(row, power_w=None) if row.source == "helios" and row.start == EPOCH + timedelta(hours=12)
                        else row for row in second_forecasts]
    report = evaluate(first_forecasts + second_forecasts, actuals, first_windows + second_windows)
    checks = report["improvement"]["helios"]["daily_win_by_inverter_horizon"]
    assert set(checks) == {"wr|day_1_at_00:00"}
    check = checks["wr|day_1_at_00:00"]
    assert check["expected_target_days"] == 32
    assert check["paired_target_days"] == check["winning_target_days"] == 31
    assert check["daily_win_fraction"] == 1


@pytest.mark.parametrize("missing_origin", [True, False])
def test_minimum_target_days_requires_every_declared_origin_without_bootstrap(missing_origin):
    forecasts, actuals, windows = archive(days=30)
    first_windows = [replace(row, cutoff=row.cutoff - timedelta(days=1)) for row in windows]
    second_windows = [replace(row, cutoff=row.cutoff - timedelta(days=1) + timedelta(seconds=30))
                      for row in windows]
    first_forecasts = [replace(row, issued_at=row.issued_at - timedelta(days=1)) for row in forecasts]
    second_forecasts = [replace(row, issued_at=row.issued_at - timedelta(days=1) + timedelta(seconds=30))
                        for row in forecasts]
    if missing_origin:
        second_forecasts = [replace(row, power_w=None)
                            if row.source == "helios" and row.start == EPOCH + timedelta(hours=12)
                            else row for row in second_forecasts]
    report = evaluate(first_forecasts + second_forecasts, actuals, first_windows + second_windows)
    expected_days = 29 if missing_origin else 30
    key = "wr|day_1_at_00:00"
    assert report["coverage"] > report["policy"]["min_coverage"]
    assert report["paired_target_days"] == 30  # Interval availability is a separate numerator.
    assert report["strata"][key]["complete_target_days"] == expected_days
    for source in ("helios", "open_meteo"):
        check = report["improvement"][source]["daily_win_by_inverter_horizon"][key]
        assert check["expected_target_days"] == 30
        assert check["paired_target_days"] == check["winning_target_days"] == expected_days
        assert check["daily_win_fraction"] == 1
        assert check["passed"] is (not missing_origin)
        assert report["improvement"][source]["supports_improvement_on_paired_archive"] is (not missing_origin)
    assert report["comparison_eligible"] is (not missing_origin)
    assert report["supports_improvement_over_both_references_on_paired_archive"] is (not missing_origin)
    assert report["statistical_acceptance"] == "not_evaluated"
    if missing_origin:
        assert "insufficient_per_horizon_inverter_days" in report["gate_reasons"]
        assert check["gate_reasons"] == ["insufficient_complete_paired_target_days"]


def test_distinct_forecast_tasks_have_explicit_exposure_scope_not_extra_independent_days():
    from custom_components.adaptive_solar.core.statistical_validation import paired_day_bootstrap

    forecasts, actuals, windows = archive()
    baseline = evaluate(forecasts, actuals, windows)
    forecasts += [replace(row, issued_at=row.issued_at - timedelta(days=1)) for row in forecasts]
    windows += [replace(row, cutoff=row.cutoff - timedelta(days=1)) for row in windows]
    report = evaluate(forecasts, actuals, windows)
    policy = report["policy"]
    assert policy["interval_task_identity"] == ["cutoff", "inverter_id", "start", "end"]
    assert policy["interval_count_scope"] == "declared_forecast_tasks_not_independent_samples"
    assert policy["interval_weighting"] == "forecast_task_duration_hours"
    assert policy["interval_energy_scope"] == "forecast_task_exposure_not_unique_generation"
    assert report["paired_intervals"] == 2 * baseline["paired_intervals"]
    for source in SOURCES:
        score, original = report["scores"][source]["overall"], baseline["scores"][source]["overall"]
        assert score["mae_w"] == original["mae_w"]
        assert score["actual_energy_kwh"] == 2 * original["actual_energy_kwh"]
    assert evaluate(forecasts * 2, actuals * 2, windows * 2) == report
    bootstrap = paired_day_bootstrap(report)
    assert bootstrap["joint_target_day_count"] == 32
    assert bootstrap["accepted"]  # Both predeclared energy strata still pass.


def test_identical_complete_pairs_gate_and_metrics_are_json_serializable():
    report = evaluate(*archive())
    assert report["comparison_eligible"]
    assert report["paired_intervals"] == 32 * 24
    assert report["scores"]["adaptive"]["overall"]["mae_w"] == 5
    assert report["scores"]["adaptive"]["overall"]["bias_w"] == 5
    assert report["scores"]["adaptive"]["daily_energy"]["mae_kwh"] == pytest.approx(0.12)
    assert report["improvement"]["helios"]["supports_improvement_on_paired_archive"]
    assert report["scores"]["adaptive"]["by_lead"]["0-6h"]["count"] == 32 * 6
    assert report["scores"]["adaptive"]["by_inverter"]["wr"]["count"] == 32 * 24
    json.dumps(report, allow_nan=False)


def test_missing_competitor_is_a_gap_for_every_source_not_zero_or_selected_pair():
    forecasts, actuals, windows = archive()
    forecasts = [row for row in forecasts if row.source != "helios" or row.start.hour != 12]
    report = evaluate(forecasts, actuals, windows)
    assert report["paired_intervals"] == 32 * 23
    assert all(report["scores"][source]["overall"]["count"] == 32 * 23 for source in SOURCES)
    assert report["scores"]["adaptive"]["daily_energy"]["count"] == 0
    assert not report["comparison_eligible"]
    assert not report["improvement"]["helios"]["supports_improvement_on_paired_archive"]
    assert report["missing"][0]["missing_sources"] == ["helios"]
    daily_win = report["improvement"]["helios"]["daily_win_by_inverter_horizon"]["wr|day_0_at_00:00"]
    assert daily_win["daily_win_fraction"] is None
    assert daily_win["paired_target_days"] == 0
    assert daily_win["gate_reasons"] == ["no_complete_paired_target_days"]
    assert report["improvement"]["helios"]["daily_win_fraction"] is None


def test_post_cutoff_forecasts_and_unfinalized_actuals_cannot_leak_into_scores():
    forecasts, actuals, windows = archive(days=1)
    future = [replace(row, issued_at=row.issued_at + timedelta(minutes=1), power_w=500)
              for row in forecasts]
    report = evaluate(forecasts + future, actuals, windows)
    assert report["scores"]["adaptive"]["overall"]["mae_w"] == 5
    # Labels are visible only after observation finalization, even though the
    # target interval has already ended.
    late = [replace(row, observed_at=EPOCH + timedelta(days=500)) for row in actuals]
    report = evaluate(forecasts, late, windows)
    assert report["paired_intervals"] == 0
    assert report["scores"]["adaptive"]["overall"]["mae_w"] is None
    json.dumps(report, allow_nan=False)


def test_ambiguous_duplicates_and_latest_unavailable_issue_fail_closed():
    forecasts, actuals, windows = archive(days=1)
    chosen = next(row for row in forecasts if row.source == "adaptive" and row.start.hour == 12)
    report = evaluate(forecasts + [replace(chosen, power_w=200)], actuals, windows)
    assert report["paired_intervals"] == 23
    # A newer unavailable issue cannot be replaced with an older favorable one.
    window = EvaluationWindow(EPOCH + timedelta(hours=11), chosen.start, chosen.end, "wr")
    latest = replace(chosen, issued_at=EPOCH + timedelta(hours=10), power_w=None)
    report = evaluate(forecasts + [latest], actuals, [window])
    assert report["paired_intervals"] == 0
    assert report["missing"][0]["missing_sources"] == ["adaptive"]


@pytest.mark.parametrize("cutoff_offset_us,paired", [(-1, 1), (0, 0), (1, 0)])
def test_empty_attempt_blocks_older_curve_at_its_exact_availability(cutoff_offset_us, paired):
    forecasts, actuals, windows = archive(days=1)
    target = windows[12]
    available = EPOCH + timedelta(hours=11)
    window = replace(target, cutoff=available + timedelta(microseconds=cutoff_offset_us))
    attempts = [ForecastAttempt("adaptive", available, "wr"),
                ForecastAttempt("physics", available, "other-stage")]

    report = evaluate(forecasts, actuals, [window], forecast_attempts=attempts)

    assert report["paired_intervals"] == paired
    assert report["source_available_intervals"] == {source: paired if source == "adaptive" else 1
                                                     for source in SOURCES}
    if not paired:
        assert report["missing"][0]["missing_sources"] == ["adaptive"]


def test_curtailment_and_actual_gaps_cannot_generate_complete_day_energy():
    forecasts, actuals, windows = archive(days=1)
    actuals[12] = replace(actuals[12], curtailed=True)
    report = evaluate(forecasts, actuals, windows)
    assert report["excluded"]["curtailed"] == 1
    assert report["paired_intervals"] == 23
    assert report["scores"]["adaptive"]["daily_energy"]["count"] == 0
    report = evaluate(forecasts, actuals[:10], windows)
    assert report["paired_intervals"] == 10
    assert report["coverage"] == pytest.approx(10 / 24)


def test_piecewise_hourly_forecasts_integrate_against_quarter_hour_actuals():
    start, end = EPOCH + timedelta(hours=12), EPOCH + timedelta(hours=13)
    forecasts = [ForecastRecord(source, EPOCH, start, end, "wr", 100) for source in SOURCES]
    actuals = [ActualRecord(start + timedelta(minutes=15 * i), start + timedelta(minutes=15 * (i + 1)),
                            "wr", 80 + 10 * i, end) for i in range(4)]
    window = EvaluationWindow(EPOCH, start, end, "wr")
    report = evaluate(forecasts, actuals, [window])
    assert report["scores"]["adaptive"]["overall"]["mae_w"] == 5
    # A 15-minute target uses the archived hourly interval mean without
    # fabricating finer meteorological information.
    quarter = replace(window, end=start + timedelta(minutes=15))
    report = evaluate(forecasts, actuals, [quarter])
    assert report["scores"]["adaptive"]["overall"]["mae_w"] == 20
    report = evaluate(forecasts, actuals[1:], [window])
    assert report["paired_intervals"] == 0


@pytest.mark.parametrize("actual_spans,window_span", [
    ([(0, 60)], (15, 45)),  # Window strictly inside one observed mean.
    ([(-15, 15), (15, 60)], (0, 60)),  # First observation crosses the left edge.
    ([(0, 45), (45, 75)], (0, 60)),  # Last observation crosses the right edge.
])
def test_observed_means_never_create_unmeasured_edge_fragment_energy(actual_spans, window_span):
    start = EPOCH + timedelta(hours=12)
    left, right = (start + timedelta(minutes=minutes) for minutes in window_span)
    actuals = [ActualRecord(start + timedelta(minutes=a), start + timedelta(minutes=b),
                            "wr", 1000, start + timedelta(hours=2)) for a, b in actual_spans]
    forecasts = [ForecastRecord(source, EPOCH, left, right, "wr", 1000) for source in SOURCES]
    report = evaluate(forecasts, actuals, [EvaluationWindow(EPOCH, left, right, "wr")])
    assert report["paired_intervals"] == 0
    assert report["missing"][0]["missing_actual"]
    assert report["scores"]["adaptive"]["overall"]["actual_energy_kwh"] is None
    assert report["scores"]["adaptive"]["overall"]["mae_w"] is None


def test_full_hour_actual_aggregates_quarter_hour_forecasts_without_splitting_actual():
    start, end = EPOCH + timedelta(hours=12), EPOCH + timedelta(hours=13)
    actual = ActualRecord(start, end, "wr", 1000, end)
    forecasts = [ForecastRecord(source, EPOCH, start + timedelta(minutes=15 * index),
                                start + timedelta(minutes=15 * (index + 1)), "wr", power)
                 for source in SOURCES for index, power in enumerate((0, 0, 2000, 2000))]
    report = evaluate(forecasts, [actual], [EvaluationWindow(EPOCH, start, end, "wr")])
    assert report["paired_intervals"] == 1
    assert report["scores"]["adaptive"]["overall"]["mae_w"] == 0
    assert report["scores"]["adaptive"]["overall"]["actual_energy_kwh"] == 1


@pytest.mark.parametrize("date, hours", [("2025-03-30", 23), ("2025-10-26", 25)])
def test_local_daily_energy_uses_real_dst_day_duration(date, hours):
    tz = ZoneInfo("Europe/Berlin")
    start = datetime.fromisoformat(date).replace(tzinfo=tz).astimezone(timezone.utc)
    next_day = (datetime.fromisoformat(date) + timedelta(days=1)).replace(tzinfo=tz).astimezone(timezone.utc)
    window = EvaluationWindow(start, start, next_day, "wr")
    actual = ActualRecord(start, next_day, "wr", 1000, next_day)
    forecasts = [ForecastRecord(source, start, start, next_day, "wr", 1100) for source in SOURCES]
    report = evaluate(forecasts, [actual], [window], timezone_name="Europe/Berlin")
    pair = report["energy_pairs"][0]
    assert pair["actual_kwh"] == hours
    assert pair["forecasts_kwh"]["adaptive"] == pytest.approx(hours * 1.1)


def test_rest_of_day_energy_and_declared_schedule_validation():
    forecasts, actuals, windows = archive(days=1)
    cutoff = EPOCH + timedelta(hours=12)
    windows = [replace(window, cutoff=cutoff) for window in windows if window.start >= cutoff]
    report = evaluate(forecasts, actuals, windows)
    assert report["scores"]["adaptive"]["rest_of_day_energy"]["count"] == 1
    assert report["scores"]["adaptive"]["rest_of_day_energy"]["mae_kwh"] == pytest.approx(0.06)
    assert report["scores"]["adaptive"]["daily_energy"]["count"] == 0
    with pytest.raises(ValueError, match="overlapping"):
        evaluate(forecasts, actuals, windows + [replace(windows[0], end=windows[0].end + timedelta(minutes=5))])
    with pytest.raises(ValueError):
        EvaluationWindow(cutoff, EPOCH, cutoff, "wr")


def test_record_json_roundtrips_and_short_biased_archive_does_not_claim_improvement():
    forecasts, actuals, windows = archive(days=1)
    assert ForecastRecord.from_dict(forecasts[0].to_dict()) == forecasts[0]
    assert ActualRecord.from_dict(actuals[0].to_dict()) == actuals[0]
    assert EvaluationWindow.from_dict(windows[0].to_dict()) == windows[0]
    report = evaluate(forecasts, actuals, windows)
    assert not report["comparison_eligible"]
    assert "insufficient_complete_paired_days" in report["gate_reasons"]
    assert not any(x["supports_improvement_on_paired_archive"] for x in report["improvement"].values())


def test_rest_only_evaluation_has_its_own_complete_day_and_horizon_gate():
    forecasts, actuals, windows = archive()
    windows = [replace(window, cutoff=window.cutoff + timedelta(hours=12),
                       daylight=window.start.hour < 18)
               for window in windows if window.start.hour >= 12]
    report = evaluate(forecasts, actuals, windows)
    assert report["comparison_eligible"]
    assert report["complete_daily_target_days"] == 0
    assert report["strata"]["wr|rest_of_day_12:00"]["complete_target_days"] == 32
    assert report["scores"]["adaptive"]["daylight_intervals"]["count"] == 32 * 6
    assert report["scores"]["adaptive"]["night_intervals"]["count"] == 32 * 6
    assert report["supports_improvement_over_both_references_on_paired_archive"]


def test_good_aggregate_cannot_hide_a_worse_inverter():
    forecasts, actuals, windows = archive()
    second_actuals = [replace(row, inverter_id="wr2") for row in actuals]
    second_windows = [replace(row, inverter_id="wr2") for row in windows]
    second_forecasts = [replace(row, inverter_id="wr2", power_w=(500 + (20 if row.source == "adaptive" else 10))
                               if 6 <= row.start.hour < 18 else 0) for row in forecasts]
    report = evaluate(forecasts + second_forecasts, actuals + second_actuals, windows + second_windows)
    assert report["comparison_eligible"]
    assert report["scores"]["adaptive"]["overall"]["mae_w"] < report["scores"]["helios"]["overall"]["mae_w"]
    assert not report["improvement"]["helios"]["supports_improvement_on_paired_archive"]
    assert not report["improvement"]["helios"]["by_inverter_horizon"]["wr2|day_0_at_00:00"]


def test_extra_horizon_with_too_few_days_cannot_borrow_other_horizon_evidence():
    forecasts, actuals, windows = archive()
    extra_windows = [replace(row, cutoff=row.cutoff - timedelta(days=1)) for row in windows[:5 * 24]]
    extra_forecasts = [replace(row, issued_at=row.issued_at - timedelta(days=1)) for row in forecasts[:5 * 24 * 4]]
    report = evaluate(forecasts + extra_forecasts, actuals, windows + extra_windows)
    assert report["paired_target_days"] == 32
    assert report["strata"]["wr|day_1_at_00:00"]["complete_target_days"] == 5
    assert not report["comparison_eligible"]
    assert "insufficient_per_horizon_inverter_days" in report["gate_reasons"]


def test_boolean_power_is_missing_and_curtailment_flag_has_strict_type():
    forecasts, actuals, windows = archive(days=1)
    forecasts[0] = replace(forecasts[0], power_w=True)
    report = evaluate(forecasts, actuals, windows)
    assert report["paired_intervals"] == 23
    assert report["missing"][0]["missing_sources"] == ["adaptive"]
    with pytest.raises(ValueError, match="curtailed"):
        replace(actuals[0], curtailed="false")


@pytest.mark.parametrize("target_day,expected_hours", [("2025-03-30", 23), ("2025-06-01", 24), ("2025-10-26", 25)])
def test_full_local_day_lead_uses_common_cutoff_to_real_interval_midpoint(target_day, expected_hours):
    zone = ZoneInfo("Europe/Berlin")
    day = datetime.fromisoformat(target_day)
    start = day.replace(tzinfo=zone).astimezone(timezone.utc)
    end = (day + timedelta(days=1)).replace(tzinfo=zone).astimezone(timezone.utc)
    window = EvaluationWindow(start, start, end, "wr")
    actual = ActualRecord(start, end, "wr", 1000, end)
    forecasts = [ForecastRecord(source, start - timedelta(hours=index * 48), start, end, "wr", 1100)
                 for index, source in enumerate(SOURCES)]
    report = evaluate(forecasts, [actual], [window], timezone_name="Europe/Berlin")
    assert (end - start).total_seconds() == expected_hours * 3600
    assert report["policy"]["lead_reference"] == "declared_cutoff_to_target_interval_midpoint"
    for source in SOURCES:
        assert set(report["scores"][source]["by_lead"]) == {"6-24h"}
        assert set(report["scores"][source]["by_inverter_lead"]) == {"wr|6-24h"}


@pytest.mark.parametrize("boundary,lower,upper", [(6, "0-6h", "6-24h"), (24, "6-24h", "24-48h"),
                                                 (48, "24-48h", "48-96h"), (96, "48-96h", "96h+")])
@pytest.mark.parametrize("offset_minutes", [-1, 0, 1])
def test_nonhour_cutoff_midpoint_bin_boundaries_match_learner_for_every_source(boundary, lower, upper, offset_minutes):
    from custom_components.adaptive_solar.core.learning import LEAD_BIN_NAMES, lead_bin
    from custom_components.adaptive_solar.core.models import midpoint_lead_hours

    start = EPOCH + timedelta(days=5, hours=12, minutes=20)
    end = start + timedelta(hours=1)
    cutoff = start + timedelta(minutes=30) - timedelta(hours=boundary) + timedelta(minutes=offset_minutes)
    expected = lower if offset_minutes > 0 else upper
    window = EvaluationWindow(cutoff, start, end, "wr")
    actual = ActualRecord(start, end, "wr", 1000, end)
    forecasts = [ForecastRecord(source, cutoff - timedelta(hours=index * 100), start, end, "wr", 1100)
                 for index, source in enumerate(SOURCES)]
    report = evaluate(forecasts, [actual], [window])
    assert expected == LEAD_BIN_NAMES[lead_bin(midpoint_lead_hours(cutoff, start, end))]
    for source in SOURCES:
        assert set(report["scores"][source]["by_lead"]) == {expected}
        assert set(report["scores"][source]["by_inverter_lead"]) == {f"wr|{expected}"}


def test_descriptive_gate_cannot_mix_worse_midpoint_bin_with_better_long_window():
    forecasts, actuals, windows = [], [], []
    for day in range(32):
        cutoff = EPOCH + timedelta(days=day)
        # Both starts used to be in 0-6h. Their means represent 2h versus 14h
        # leads, so the first regression needs its own performance guard.
        for left, right, candidate_error, reference_error in ((0, 4, 100, 10), (4, 24, 10, 100)):
            start, end = cutoff + timedelta(hours=left), cutoff + timedelta(hours=right)
            windows.append(EvaluationWindow(cutoff, start, end, "wr"))
            actuals.append(ActualRecord(start, end, "wr", 1000, end))
            for source in SOURCES:
                error = candidate_error if source == "adaptive" else reference_error
                forecasts.append(ForecastRecord(source, cutoff, start, end, "wr", 1000 + error))
    report = evaluate(forecasts, actuals, windows, min_paired_intervals=1)
    assert report["comparison_eligible"]
    assert report["scores"]["adaptive"]["overall"]["mae_w"] < report["scores"]["helios"]["overall"]["mae_w"]
    for source in ("helios", "open_meteo"):
        improvement = report["improvement"][source]
        assert improvement["by_inverter_horizon"]["wr|day_0_at_00:00"]
        assert not improvement["by_inverter_lead"]["wr|0-6h"]
        assert improvement["by_inverter_lead"]["wr|6-24h"]
        assert not improvement["supports_improvement_on_paired_archive"]
    assert not report["supports_improvement_over_both_references_on_paired_archive"]
