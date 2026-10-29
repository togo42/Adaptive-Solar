"""Behavior of the offline guard; synthetic cases do not prove forecast skill."""
from dataclasses import replace
from datetime import timedelta
import math

import pytest

from custom_components.adaptive_solar.core.learning import ResidualLearner
from custom_components.adaptive_solar.core.learning_support import SupportGuardLearner, SupportPolicy
from tests.test_learning import EPOCH, synthetic_days
from tests.test_learning_regimes import regimes


@pytest.fixture(scope="module")
def fitted():
    rows = synthetic_days(count=28)
    cutoff = EPOCH + timedelta(days=28)
    return (SupportGuardLearner().fit(rows, cutoff), ResidualLearner().fit(rows, cutoff))


def test_supported_prediction_and_reference_status_remain_exact_even_for_large_correction(fitted):
    guard, reference = fitted
    row = synthetic_days(first=28, count=1)[0]
    args = (row.inverter_id, row.features, row.baseline_w, 2000)
    expected = reference.predict(*args)
    assert guard.status == reference.status
    assert guard.reference_predict(*args) == guard.predict(*args) == expected
    assert guard.assess(*args).supported is True
    radius = guard.status["wr"]["lead_bins"]["6-24h"]["calibration_radius_w"]
    assert abs(expected.power_w - row.baseline_w) > 100 * radius


@pytest.mark.parametrize("changed", [{"cloud_cover_pct": 100}, {"baseline_w": 1900},
                                     {"temperature_c": -30}, {"wind_m_s": 25}])
def test_new_marginal_lage_falls_back_without_borrowing_reference_bounds(fitted, changed):
    guard, reference = fitted
    row = synthetic_days(first=28, count=1)[0]
    features = {**row.features, **changed}
    baseline = features["baseline_w"]
    assert reference.predict("wr", features, baseline, 2000).status == "residual_empirical_calibration"
    result = guard.predict("wr", features, baseline, 2000)
    assessment = guard.assess("wr", features, baseline, 2000)
    assert assessment.supported is False and assessment.reason == "marginal_range"
    assert set(changed) <= set(assessment.outside_features)
    assert result.power_w == baseline
    assert result.status == "physics_support_marginal_range"
    assert result.lower_w is result.upper_w is None


def test_constant_features_allow_declared_small_measurement_variation(fitted):
    guard, _ = fitted
    row = synthetic_days(first=28, count=1)[0]
    features = {**row.features, "cloud_cover_pct": 12, "wind_m_s": 2.2}
    assert guard.assess("wr", features, row.baseline_w, 2000).supported is True


def test_season_tolerance_allows_normal_progression_past_two_long_holdout_blocks():
    # At the archive's 120-day bound each withheld block has 24 days. A
    # shorter-than-48-day angular allowance would reject every current query.
    guard = SupportGuardLearner().fit(synthetic_days(count=120), EPOCH + timedelta(days=120))
    row = synthetic_days(first=127, count=1)[0]
    assert guard.assess("wr", row.features, row.baseline_w, 2000).supported is True


def test_holdout_and_future_features_cannot_expand_training_support():
    rows = synthetic_days(count=28)
    altered = [replace(row, features={**row.features, "cloud_cover_pct": 100})
               if row.start >= EPOCH + timedelta(days=18) else row for row in rows]
    future = [replace(row, features={**row.features, "cloud_cover_pct": 50})
              for row in synthetic_days(first=28, count=5)]
    cutoff = EPOCH + timedelta(days=28)
    original = SupportGuardLearner().fit(rows, cutoff)
    candidate = SupportGuardLearner().fit(altered + future, cutoff)
    assert candidate.support_report() == original.support_report()
    cell = candidate.support_report()["cells"]["wr"]["nwp"]["6-24h"]
    assert cell["training_target_days"] == 18
    assert cell["training_target_hours"] == 216
    assert cell["envelope"]["cloud_cover_pct"] == {"lower": 5, "upper": 15, "joint_scale": 5}
    assert cell["latest_training_observed_at"] < candidate.status["wr"]["validation_start"]


def test_duplicate_reports_and_rejected_rows_cannot_change_support_or_predictions():
    rows = synthetic_days(count=28)
    cutoff = EPOCH + timedelta(days=28)
    reference = SupportGuardLearner().fit(rows, cutoff)
    rejected = [replace(row, actual_w=0, curtailed=True,
                        features={**row.features, "cloud_cover_pct": 99}) for row in rows]
    duplicate = SupportGuardLearner().fit(rows * 4 + rejected, cutoff)
    assert duplicate.support_report() == reference.support_report()
    row = rows[100]
    assert duplicate.predict("wr", row.features, row.baseline_w, 2000) == reference.predict("wr", row.features, row.baseline_w, 2000)


def test_unseen_feature_combination_is_rejected_inside_all_marginal_ranges():
    rows = [replace(row, features={**row.features, "cloud_cover_pct": row.baseline_w / 20})
            for row in synthetic_days(count=28)]
    guard = SupportGuardLearner().fit(rows, EPOCH + timedelta(days=28))
    row = rows[0]
    features = {**row.features, "cloud_cover_pct": 70}
    assessment = guard.assess("wr", features, row.baseline_w, 2000)
    assert not assessment.outside_features
    assert assessment.supported is False and assessment.reason == "joint_distance"
    assert assessment.nearest_distance > 1
    assert guard.predict("wr", features, row.baseline_w, 2000).power_w == row.baseline_w


def test_circular_year_and_azimuth_seams_do_not_create_artificial_extrapolation():
    rows = []
    for index, row in enumerate(synthetic_days(count=28)):
        azimuth = math.radians(359 if index % 2 else 1)
        season = 2 * math.pi * (359 if index % 2 else 4) / 365.2425
        rows.append(replace(row, features={**row.features, "sun_azimuth_sin": math.sin(azimuth),
            "sun_azimuth_cos": math.cos(azimuth), "day_of_year_sin": math.sin(season),
            "day_of_year_cos": math.cos(season)}))
    guard = SupportGuardLearner().fit(rows, EPOCH + timedelta(days=28))
    row = rows[50]
    features = {**row.features, "sun_azimuth_sin": 0, "sun_azimuth_cos": 1,
                "day_of_year_sin": 0, "day_of_year_cos": 1}
    assert guard.assess("wr", features, row.baseline_w, 2000).supported is True
    season = 2 * math.pi * 150 / 365.2425
    distant = {**features, "day_of_year_sin": math.sin(season), "day_of_year_cos": math.cos(season)}
    assert guard.assess("wr", distant, row.baseline_w, 2000).reason == "joint_distance"


def test_invalid_circular_features_do_not_receive_empirical_bounds(fitted):
    guard, _ = fitted
    row = synthetic_days(first=28, count=1)[0]
    features = {**row.features, "sun_azimuth_sin": 100}
    assert guard.predict("wr", features, row.baseline_w, 2000).status == "physics_support_invalid_circular_features"


def test_regimes_never_share_feature_support():
    nwp, ghi = regimes(count=28)
    guard = SupportGuardLearner().fit(nwp + ghi, EPOCH + timedelta(days=28))
    assert set(guard.support_report()["cells"]["wr"]) == {"nwp", "ghi"}
    row = ghi[0]
    features = {**row.features, "ghi_nowcast_gain": 1.0}
    result = guard.predict("wr", features, row.baseline_w, 2000)
    assert result.status == "physics_support_marginal_range"
    assert "ghi_nowcast_gain" in guard.assess("wr", features, row.baseline_w, 2000).outside_features


@pytest.mark.parametrize("changed", [{"lead_hours": 100}, {"lead_hours": 6},
                                     {"cloud_cover_pct": float("nan")}, {"sun_elevation_deg": -1},
                                     {"beam_shade_factor": .4}])
def test_original_fallbacks_take_precedence_over_support_guard(fitted, changed):
    guard, reference = fitted
    row = synthetic_days(first=28, count=1)[0]
    features = {**row.features, **changed}
    args = ("wr", features, row.baseline_w, 2000)
    expected = reference.predict(*args)
    assert expected.status.startswith("physics")
    assert guard.predict(*args) == expected
    assert guard.assess(*args).supported is None


def test_refit_clears_old_support_and_unavailable_model_stays_native_fallback():
    rows = synthetic_days(count=28)
    guard = SupportGuardLearner().fit(rows, EPOCH + timedelta(days=28))
    assert guard.support_report()["cells"]
    guard.fit(rows[:12], EPOCH + timedelta(days=28))
    assert guard.support_report()["cells"] == {}
    row = rows[0]
    assert guard.predict("wr", row.features, row.baseline_w, 2000).status == "physics_insufficient_history"
    assert guard.predict("other", row.features, row.baseline_w, 2000).status == "physics_cold_start"


def test_missing_support_for_an_active_reference_fails_closed():
    class MissingCapture(SupportGuardLearner):
        def _capture_training_support(self, inverter, regime, train):
            pass

    rows = synthetic_days(count=28)
    guard = MissingCapture().fit(rows, EPOCH + timedelta(days=28))
    row = rows[0]
    assert guard.reference_predict("wr", row.features, row.baseline_w, 2000).status.startswith("residual")
    result = guard.predict("wr", row.features, row.baseline_w, 2000)
    assert result.status == "physics_support_missing_training_support"
    assert result.power_w == row.baseline_w and result.lower_w is result.upper_w is None


def test_output_cap_night_and_invalid_caps_keep_the_original_contract(fitted):
    guard, _ = fitted
    row = synthetic_days(first=28, count=1)[0]
    features = {**row.features, "baseline_w": 1900}
    result = guard.predict("wr", features, 1900, 1500)
    assert result.power_w == 1500 and result.lower_w is result.upper_w is None
    assert guard.predict("wr", features, 1900, 0).power_w == 0
    assert guard.predict("wr", {**features, "baseline_w": 0}, 0, 1500).status == "physics_night"
    with pytest.raises(ValueError, match="cap_w"):
        guard.predict("wr", row.features, row.baseline_w, float("nan"))


@pytest.mark.parametrize("start", [(2026, 3, 15), (2026, 10, 10)])
def test_training_support_preserves_utc_duration_across_both_dst_changes(start):
    from datetime import UTC, datetime

    delta = datetime(*start, tzinfo=UTC) - EPOCH
    rows = [replace(row, issued_at=row.issued_at + delta, start=row.start + delta,
                    end=row.end + delta, observed_at=row.observed_at + delta)
            for row in synthetic_days(count=28)]
    guard = SupportGuardLearner(timezone_name="Europe/Berlin").fit(rows, EPOCH + delta + timedelta(days=28))
    cell = guard.support_report()["cells"]["wr"]["nwp"]["6-24h"]
    assert cell["training_target_days"] == 18 and cell["training_target_hours"] == 216


def test_prototype_budget_is_deterministic_and_explicit():
    rows = synthetic_days(count=28)
    policy = SupportPolicy(max_prototypes=16)
    guard = SupportGuardLearner(support_policy=policy).fit(rows, EPOCH + timedelta(days=28))
    report = guard.support_report()
    cell = report["cells"]["wr"]["nwp"]["6-24h"]
    assert cell["prototype_count"] == 16 and cell["prototype_reduction"] is True
    assert report["policy_sha256"] == policy.sha256
    assert report["operational_use"] is False
    report["cells"]["wr"]["nwp"]["6-24h"]["envelope"]["baseline_w"]["lower"] = -1e6
    assert guard.support_report()["cells"]["wr"]["nwp"]["6-24h"]["envelope"]["baseline_w"]["lower"] > 0


@pytest.mark.parametrize("kwargs", [{"version": "other"}, {"max_prototypes": 0}, {"max_prototypes": True},
                                   {"season_tolerance_days": float("nan")}, {"lower_quantile": .99},
                                   {"joint_range_fraction": 0}])
def test_policy_rejects_invalid_or_unbounded_configuration(kwargs):
    with pytest.raises(ValueError):
        SupportPolicy(**kwargs)
