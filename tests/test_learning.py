"""Synthetic behavior tests; these do not establish real forecast accuracy."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import math
from zoneinfo import ZoneInfo

import pytest

from custom_components.adaptive_solar.core.learning import ResidualLearner
from custom_components.adaptive_solar.core.models import TrainingSample

EPOCH = datetime(2025, 4, 1, tzinfo=timezone.utc)


def synthetic_days(first=0, count=50, *, unshaded=False):
    rows = []
    for day in range(first, first + count):
        issue = EPOCH + timedelta(days=day)
        for hour in range(6, 18):
            start = issue + timedelta(hours=hour)
            elevation = 50 * math.sin(math.pi * (hour - 5) / 14)
            azimuth = math.radians(80 + (hour - 6) * 17)
            baseline = 1400 * math.sin(math.pi * (hour - 5) / 14)
            features = {
                "baseline_w": baseline, "sun_elevation_deg": elevation,
                "sun_azimuth_sin": math.sin(azimuth), "sun_azimuth_cos": math.cos(azimuth),
                "day_of_year_sin": math.sin(2 * math.pi * (90 + day) / 365),
                "day_of_year_cos": math.cos(2 * math.pi * (90 + day) / 365),
                "temperature_c": 18 + hour / 4, "wind_m_s": 2,
                "cloud_cover_pct": 10, "lead_hours": hour + 0.5,
            }
            # Recurring directional obstruction, observed only at shared WR.
            actual = baseline if unshaded else baseline * (0.35 if hour < 10 else 0.9)
            rows.append(TrainingSample(issue, start, start + timedelta(hours=1),
                                       start + timedelta(hours=1, minutes=5), "wr", baseline,
                                       actual, features))
    return rows


def test_learns_recurring_shadow_on_future_days_without_future_labels():
    training = synthetic_days(count=50)
    as_of = EPOCH + timedelta(days=50)
    learner = ResidualLearner().fit(training, as_of)
    assert learner.status["wr"]["state"] == "active"
    assert learner.status["wr"]["train_end"] < learner.status["wr"]["validation_start"]
    assert learner.status["wr"]["validation_end"] < learner.status["wr"]["calibration_start"]
    holdout = synthetic_days(first=50, count=12)
    predictions = [learner.predict("wr", row.features, row.baseline_w, 2000) for row in holdout]
    model_error = sum(abs(row.actual_w - predicted.power_w) for row, predicted in zip(holdout, predictions))
    physics_error = sum(abs(row.actual_w - row.baseline_w) for row in holdout)
    assert model_error < physics_error * 0.2
    assert all(predicted.lower_w is not None and predicted.lower_w <= predicted.power_w <= predicted.upper_w
               for predicted in predictions)
    # Deliberately wrong future targets cannot affect this as-of fit.
    contaminated = training + [replace(row, actual_w=1900) for row in holdout]
    second = ResidualLearner().fit(contaminated, as_of)
    assert second.status["wr"]["unique_intervals"] == len(training)
    assert second.predict("wr", holdout[0].features, holdout[0].baseline_w, 2000).power_w == predictions[0].power_w


def test_cold_start_and_validation_rejection_have_no_invented_uncertainty():
    short = synthetic_days(count=4)
    learner = ResidualLearner().fit(short, EPOCH + timedelta(days=50))
    row = short[0]
    prediction = learner.predict("wr", row.features, row.baseline_w, 2000)
    assert prediction.power_w == row.baseline_w
    assert prediction.lower_w is prediction.upper_w is None
    assert learner.status["wr"]["state"] == "insufficient_history"
    perfect_physics = synthetic_days(unshaded=True)
    learner.fit(perfect_physics, EPOCH + timedelta(days=50))
    assert learner.status["wr"]["state"] == "rejected_validation"
    assert learner.predict("wr", row.features, row.baseline_w, 2000).lower_w is None


def test_historical_shadow_pattern_is_rejected_when_later_validation_has_no_shadow():
    rows = synthetic_days(count=30) + synthetic_days(first=30, count=20, unshaded=True)
    learner = ResidualLearner().fit(rows, EPOCH + timedelta(days=50))
    assert learner.status["wr"]["state"] == "rejected_validation"
    assert learner.status["wr"]["physics_validation_mae_w"] == 0
    assert learner.status["wr"]["residual_validation_mae_w"] > 100


def test_excludes_curtailment_and_duplicate_issues_do_not_inflate_history():
    rows = synthetic_days()
    clean = ResidualLearner().fit(rows, EPOCH + timedelta(days=50))
    duplicates = rows * 5
    # Bad labels are excluded explicitly, even when they would support a very
    # different correction. Different issue times do not bypass curtailment.
    curtailed = [replace(row, actual_w=0, curtailed=True,
                         issued_at=row.issued_at - timedelta(hours=1)) for row in rows]
    learner = ResidualLearner().fit(duplicates + curtailed, EPOCH + timedelta(days=50))
    assert learner.status["wr"]["unique_intervals"] == len(rows)
    assert learner.status["wr"]["issues"] == len(rows)
    assert learner.status["wr"]["rejected_rows"] == len(rows)
    row = rows[0]
    assert learner.predict("wr", row.features, row.baseline_w, 2000) == clean.predict("wr", row.features, row.baseline_w, 2000)


def test_conflicting_labels_are_dropped_and_frequency_cannot_create_days():
    rows = synthetic_days(count=5)
    quarters = [replace(row, start=row.start + timedelta(minutes=15 * quarter),
                        end=row.start + timedelta(minutes=15 * (quarter + 1)))
                for row in rows for quarter in range(4)]
    learner = ResidualLearner().fit(quarters, EPOCH + timedelta(days=50))
    assert learner.status["wr"]["unique_target_hours"] == 0
    assert learner.status["wr"]["rejected_rows"] == len(quarters)
    assert learner.status["wr"]["state"] == "insufficient_history"
    learner.fit(rows + [replace(row, actual_w=row.actual_w + 10) for row in rows], EPOCH + timedelta(days=50))
    assert learner.status["wr"]["unique_intervals"] == 0


def test_night_missing_features_and_caps_are_safe():
    rows = synthetic_days()
    learner = ResidualLearner().fit(rows, EPOCH + timedelta(days=50))
    row = rows[0]
    assert learner.predict("wr", {**row.features, "sun_elevation_deg": -1}, row.baseline_w, 2000).power_w == 0
    invalid = learner.predict("wr", {**row.features, "wind_m_s": float("nan")}, row.baseline_w, 2000)
    assert invalid.power_w == row.baseline_w and invalid.lower_w is None
    assert 0 <= learner.predict("wr", row.features, row.baseline_w, 100).power_w <= 100
    with pytest.raises(ValueError):
        learner.fit(rows, datetime(2025, 5, 1))
    with pytest.raises(ValueError):
        learner.predict("wr", row.features, row.baseline_w, float("nan"))


def test_labels_after_as_of_and_current_interval_issues_are_excluded():
    rows = synthetic_days(count=4)
    after = [replace(row, observed_at=EPOCH + timedelta(days=100)) for row in rows]
    late_issue = [replace(row, issued_at=row.start + timedelta(minutes=5)) for row in rows]
    learner = ResidualLearner().fit(after + late_issue, EPOCH + timedelta(days=50))
    assert learner.status["wr"]["unique_intervals"] == 0
    assert learner.status["wr"]["rejected_rows"] == 2 * len(rows)


def long_lead_rows(rows):
    """Same measured targets, separately archived forecasts five days earlier."""
    return [replace(row, issued_at=row.issued_at - timedelta(days=5),
                    features={**row.features, "lead_hours": row.features["lead_hours"] + 120})
            for row in rows]


def test_near_term_history_cannot_activate_or_calibrate_unknown_multiday_bin():
    rows = synthetic_days()
    learner = ResidualLearner().fit(rows, EPOCH + timedelta(days=50))
    row = synthetic_days(first=50, count=1)[0]
    features = {**row.features, "lead_hours": 120}
    prediction = learner.predict("wr", features, row.baseline_w, 2000)
    assert learner.status["wr"]["lead_bins"]["6-24h"]["state"] == "active"
    assert learner.status["wr"]["lead_bins"]["96h+"]["state"] == "insufficient_validation"
    assert prediction.power_w == row.baseline_w
    assert prediction.status == "physics_lead_insufficient_validation"
    assert prediction.lower_w is prediction.upper_w is None


def test_archived_multiday_arm_has_own_validation_and_future_synthetic_holdout():
    near = synthetic_days()
    learner = ResidualLearner().fit(near + long_lead_rows(near), EPOCH + timedelta(days=50))
    bins = learner.status["wr"]["lead_bins"]
    assert bins["96h+"]["state"] == "active"
    assert bins["96h+"]["validation_target_days"] == 10
    assert bins["96h+"]["calibration_target_days"] == 10
    assert bins["96h+"]["calibration_radius_w"] is not None
    # Two issue arms still represent only 600 distinct measured intervals.
    assert learner.status["wr"]["unique_intervals"] == 600
    # The five-day forecast origins themselves also follow the fit cutoff;
    # labels between an earlier issue and the fit must never aid a past issue.
    future = long_lead_rows(synthetic_days(first=55, count=10))
    assert all(row.issued_at >= EPOCH + timedelta(days=50) for row in future)
    predictions = [learner.predict("wr", row.features, row.baseline_w, 2000) for row in future]
    assert all(prediction.status == "residual_empirical_calibration" for prediction in predictions)
    assert sum(abs(prediction.power_w - row.actual_w) for row, prediction in zip(future, predictions)) < sum(
        abs(row.baseline_w - row.actual_w) for row in future) * 0.2


def test_multiday_calibration_does_not_borrow_near_term_error_radius():
    near = synthetic_days()
    far = long_lead_rows([row for row in near if row.start < EPOCH + timedelta(days=40)])
    learner = ResidualLearner().fit(near + far, EPOCH + timedelta(days=50))
    row = long_lead_rows(synthetic_days(first=55, count=1))[0]
    prediction = learner.predict("wr", row.features, row.baseline_w, 2000)
    assert learner.status["wr"]["lead_bins"]["96h+"]["state"] == "active"
    assert learner.status["wr"]["lead_bins"]["96h+"]["calibration_target_hours"] == 0
    assert learner.status["wr"]["lead_bins"]["6-24h"]["calibration_radius_w"] is not None
    assert prediction.status == "residual_no_uncertainty"
    assert prediction.lower_w is prediction.upper_w is None


def test_bad_multiday_bin_is_rejected_even_when_overall_validation_improves():
    near = synthetic_days()
    far = long_lead_rows(near)
    far = [replace(row, baseline_w=row.actual_w, features={**row.features, "baseline_w": row.actual_w})
           if row.start >= EPOCH + timedelta(days=30) else row for row in far]
    learner = ResidualLearner().fit(near + far, EPOCH + timedelta(days=50))
    assert learner.status["wr"]["state"] == "active"
    assert learner.status["wr"]["lead_bins"]["6-24h"]["state"] == "active"
    assert learner.status["wr"]["lead_bins"]["96h+"]["state"] == "rejected_validation"
    row = far[-1]
    prediction = learner.predict("wr", row.features, row.baseline_w, 2000)
    assert prediction.power_w == row.baseline_w
    assert prediction.status == "physics_lead_rejected_validation"
    assert prediction.lower_w is prediction.upper_w is None


def status_regime_rows(regime, *, active=True, first=0, count=50):
    """One real target, two prospective baselines with different issue times."""
    result = []
    for row in synthetic_days(first=first, count=count):
        actual = row.actual_w * 0.6
        baseline = row.baseline_w * (0.6 if regime == "ghi" else 1)
        if not active and row.start >= EPOCH + timedelta(days=30):
            baseline = actual  # Perfect physics in held-out days rejects ML.
        lead = 1.2 if regime == "ghi" else 1.4
        features = {**row.features, "baseline_w": baseline, "lead_hours": lead}
        if regime == "ghi":
            features.update(ghi_regime=1.0, ghi_nowcast_gain=0.6, ghi_observation_age_seconds=30)
        result.append(replace(row, actual_w=actual, baseline_w=baseline, features=features,
                              issued_at=row.start + (row.end - row.start) / 2 - timedelta(hours=lead)))
    return result


@pytest.mark.parametrize("nwp_active,ghi_active,primary", [
    (False, True, "ghi"), (True, False, "nwp"), (True, True, "nwp"), (False, False, "nwp"),
])
def test_flat_validation_status_belongs_to_its_named_primary_regime(nwp_active, ghi_active, primary):
    rows = {"nwp": status_regime_rows("nwp", active=nwp_active),
            "ghi": status_regime_rows("ghi", active=ghi_active)}
    as_of = EPOCH + timedelta(days=50)
    learner = ResidualLearner().fit(rows["nwp"] + rows["ghi"], as_of)
    report = learner.status["wr"]
    expected_active = [name for name, active in (("nwp", nwp_active), ("ghi", ghi_active)) if active]
    assert report["primary_regime"] == primary
    assert report["active_regimes"] == expected_active
    assert report["state"] == ("active" if expected_active else "rejected_validation")
    assert report["state"] == report["regimes"][primary]["state"]
    history_fields = {"target_days", "unique_intervals", "unique_target_hours", "issues", "rejected_rows"}
    for key, value in report["regimes"][primary].items():
        if key not in history_fields:
            assert report[key] == value, key
    assert report["history_scope"] == "deduplicated_all_regimes"
    assert report["unique_target_hours"] == report["unique_intervals"] == 600
    assert report["issues"] == 1200
    assert report["physics_validation_mae_w"] == report["regimes"][primary]["physics_validation_mae_w"]
    if expected_active:
        assert report["lead_bins"] == report["regimes"][primary]["lead_bins"]
        assert report["lead_bins"]["0-6h"]["state"] == "active"
    else:
        assert "lead_bins" not in report
    # Publishing a flat summary must neither merge nor alter the independent
    # reports, fitted models, predictions or calibrated bounds of either mode.
    for name in ("nwp", "ghi"):
        isolated = ResidualLearner().fit(rows[name], as_of)
        assert report["regimes"][name] == isolated.status["wr"]["regimes"][name]
        target = status_regime_rows(name, first=55, count=1)[0]
        actual = learner.predict("wr", target.features, target.baseline_w, 2000)
        expected = isolated.predict("wr", target.features, target.baseline_w, 2000)
        assert (actual.power_w, actual.lower_w, actual.upper_w) == (expected.power_w, expected.lower_w, expected.upper_w)


@pytest.mark.parametrize("included,primary", [(("nwp",), "nwp"), (("ghi",), "ghi"), (("nwp", "ghi"), "nwp")])
def test_inactive_short_history_has_no_invented_flat_validation_metrics(included, primary):
    rows = [row for name in included for row in status_regime_rows(name, count=4)]
    report = ResidualLearner().fit(rows, EPOCH + timedelta(days=50)).status["wr"]
    assert report["state"] == "insufficient_history"
    assert report["primary_regime"] == primary
    assert report["active_regimes"] == []
    assert report["history_scope"] == "deduplicated_all_regimes"
    assert "physics_validation_mae_w" not in report
    assert "residual_validation_mae_w" not in report
    assert "validation_daily_win_fraction" not in report
    assert "lead_bins" not in report
    assert all(value["state"] == "insufficient_history" for value in report["regimes"].values())


def midnight_rows(first):
    # Positive-sun synthetic labels isolate chronology, not actual midnight
    # irradiance at ordinary latitudes. Reuse the shadow fixture at all UTC hours.
    offset = first - EPOCH
    return [replace(row, **{field: getattr(row, field) + offset + timedelta(hours=shift)
                           for field in ("issued_at", "start", "end", "observed_at")})
            for row in synthetic_days() for shift in (-6, 6)]


@pytest.mark.parametrize("name,date,offsets", [("Asia/Kolkata", "2025-03-15", 1),
    ("Pacific/Chatham", "2025-09-10", 2), ("Australia/Adelaide", "2025-03-15", 2),
    ("Australia/Adelaide", "2025-09-10", 2), ("America/St_Johns", "2025-10-15", 2)])
def test_whole_utc_hours_crossing_local_midnight_survive_fractional_offsets_and_dst(name, date, offsets, monkeypatch):
    from custom_components.adaptive_solar.core import learning

    first, zone = datetime.fromisoformat(date).replace(tzinfo=timezone.utc), ZoneInfo(name)
    rows = midnight_rows(first)
    crossing = [row for row in rows if row.start.astimezone(zone).date()
                != (row.end - timedelta(microseconds=1)).astimezone(zone).date()]
    assert crossing and len({row.start.astimezone(zone).utcoffset() for row in rows}) == offsets
    blocks, weights = [], learning._weights
    def trace(block):
        blocks.append(block)
        return weights(block)
    monkeypatch.setattr(learning, "_weights", trace)
    learner = ResidualLearner(timezone_name=name).fit(rows, first + timedelta(days=51))
    report = learner.status["wr"]
    assert report["state"] == "active" and report["rejected_rows"] == 0
    assert report["unique_intervals"] == report["unique_target_hours"] == len(rows)
    train, validation = blocks[:2]
    calibration = [row for row in rows if row.start.astimezone(zone).date().isoformat() >= report["calibration_start"]]
    assert max(row.end for row in train) <= min(row.start for row in validation)
    assert max(row.end for row in validation) <= min(row.start for row in calibration)
    assert set(row.start for row in crossing) <= {row.start for row in train + validation + calibration}
    assert all((row.end - row.start).total_seconds() == 3600 for row in train + validation + calibration)


def test_overlapping_whole_targets_are_purged_at_both_chronological_boundaries(monkeypatch):
    from custom_components.adaptive_solar.core import learning

    zone = ZoneInfo("Asia/Kolkata")
    rows = midnight_rows(EPOCH)
    report = ResidualLearner(timezone_name=zone.key).fit(rows, EPOCH + timedelta(days=51)).status["wr"]
    removed = []
    for boundary in (report["validation_start"], report["calibration_start"]):
        after = min(row.start for row in rows if row.start.astimezone(zone).date().isoformat() >= boundary)
        before = max((row for row in rows if row.start < after), key=lambda row: row.start)
        overlapping = replace(before, end=after + timedelta(minutes=30), observed_at=after + timedelta(minutes=35))
        rows[rows.index(before)] = overlapping
        removed.append(overlapping)
    blocks, weights = [], learning._weights
    def trace(block):
        blocks.append(block)
        return weights(block)
    monkeypatch.setattr(learning, "_weights", trace)
    learner = ResidualLearner(timezone_name=zone.key).fit(rows, EPOCH + timedelta(days=51))
    report = learner.status["wr"]["regimes"]["nwp"]
    assert report["state"] == "active" and report["purged_boundary_overlap_rows"] == 2
    train, validation = blocks[:2]
    calibration = [row for row in rows if row.start.astimezone(zone).date().isoformat() >= report["calibration_start"]]
    assert max(row.end for row in train) <= min(row.start for row in validation)
    assert max(row.end for row in validation) <= min(row.start for row in calibration)
    assert not any(row in train + validation for row in removed)
    assert report["unique_target_hours"] == len(rows) - 2
    strict = ResidualLearner(timezone_name=zone.key, min_samples=len(rows)).fit(rows, EPOCH + timedelta(days=51))
    assert strict.status["wr"]["regimes"]["nwp"]["state"] == "insufficient_history"
    assert strict.status["wr"]["regimes"]["nwp"]["unique_target_hours"] == len(rows) - 2
