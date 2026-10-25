"""GHI and raw-NWP residual evidence must remain independent and prospective."""
from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_solar.coordinator import AdaptiveSolarCoordinator, join_training
from custom_components.adaptive_solar.core.learning import FEATURE_NAMES, ResidualLearner, feature_regime
from custom_components.adaptive_solar.core.models import ForecastPoint, ForecastResult, InverterConfig, SiteConfig, StringConfig
from tests.test_learning import EPOCH, synthetic_days


def regimes(first=0, count=50):
    nwp, ghi = [], []
    for row in synthetic_days(first=first, count=count):
        # Same measured AC target, separately issued raw weather and corrected
        # local-GHI baselines. Both still need directional shadow learning.
        actual = row.actual_w * 0.6
        center = row.start + (row.end - row.start) / 2
        nwp.append(replace(row, issued_at=center - timedelta(hours=1.4), actual_w=actual,
                           features={**row.features, "lead_hours": 1.4}))
        ghi.append(replace(row, issued_at=center - timedelta(hours=1.2), baseline_w=row.baseline_w * 0.6, actual_w=actual,
                           features={**row.features, "baseline_w": row.baseline_w * 0.6, "lead_hours": 1.2,
                                     "ghi_nowcast_gain": 0.6, "ghi_observation_age_seconds": 30, "ghi_regime": 1.0}))
    return nwp, ghi


def test_explicit_gain_age_regime_are_real_features_and_legacy_no_ghi_stays_nwp():
    assert {"ghi_nowcast_gain", "ghi_observation_age_seconds", "ghi_regime"} <= set(FEATURE_NAMES)
    nwp, ghi = regimes(count=1)
    assert feature_regime(nwp[0].features) == "nwp"
    assert feature_regime(ghi[0].features) == "ghi"
    old_ghi = {key: value for key, value in ghi[0].features.items() if key != "ghi_regime"}
    assert feature_regime(old_ghi) == "ghi"
    assert feature_regime({**nwp[0].features, "ghi_nowcast_gain": 0.6}) is None
    assert feature_regime({**ghi[0].features, "ghi_regime": 0}) is None
    # Clear-sky gain1 is still an observed GHI regime, never raw NWP evidence.
    assert feature_regime({**ghi[0].features, "ghi_nowcast_gain": 1, "ghi_observation_age_seconds": 0}) == "ghi"


def test_both_regimes_learn_shadow_without_doubling_unique_actual_time():
    nwp, ghi = regimes()
    learner = ResidualLearner().fit(nwp + ghi, EPOCH + timedelta(days=50))
    report = learner.status["wr"]
    assert report["state"] == "active"
    assert report["unique_target_hours"] == report["unique_intervals"] == 600
    assert report["issues"] == 1200
    assert all(report["regimes"][mode]["state"] == "active" for mode in ("nwp", "ghi"))
    future_nwp, future_ghi = regimes(first=55, count=3)
    for rows in (future_nwp, future_ghi):
        results = [learner.predict("wr", row.features, row.baseline_w, 2000) for row in rows]
        assert all(result.status.startswith("residual") for result in results)
        assert sum(abs(row.actual_w - result.power_w) for row, result in zip(rows, results)) < sum(abs(row.actual_w - row.baseline_w) for row in rows) * 0.25


@pytest.mark.parametrize("trained,missing", [("nwp", "ghi"), ("ghi", "nwp")])
def test_one_regime_cannot_activate_the_other_including_sensor_outage(trained, missing):
    nwp, ghi = regimes()
    rows = {"nwp": nwp, "ghi": ghi}
    learner = ResidualLearner().fit(rows[trained], EPOCH + timedelta(days=50))
    assert learner.status["wr"]["regimes"][trained]["state"] == "active"
    target = rows[missing][0]
    result = learner.predict("wr", target.features, target.baseline_w, 2000)
    assert result.power_w == target.baseline_w
    assert result.status == "physics_regime_insufficient_history"
    assert result.lower_w is result.upper_w is None


def test_bad_ghi_validation_does_not_borrow_good_nwp_evidence():
    nwp, ghi = regimes()
    broken = [replace(row, baseline_w=row.actual_w, features={**row.features, "baseline_w": row.actual_w})
              if row.start >= EPOCH + timedelta(days=30) else row for row in ghi]
    learner = ResidualLearner().fit(nwp + broken, EPOCH + timedelta(days=50))
    assert learner.status["wr"]["regimes"]["nwp"]["state"] == "active"
    assert learner.status["wr"]["regimes"]["ghi"]["state"] == "rejected_validation"
    row = broken[-1]
    result = learner.predict("wr", row.features, row.baseline_w, 2000)
    assert result.power_w == row.baseline_w and result.lower_w is None


def test_calibration_is_not_borrowed_from_the_other_regime():
    nwp, ghi = regimes()
    # Two GHI calibration labels/day:20h, below30h bound threshold. Its own
    # train/validation blocks remain sufficient, with50 distinct target days.
    ghi = [row for row in ghi if row.start < EPOCH + timedelta(days=40) or row.start.hour < 8]
    learner = ResidualLearner().fit(nwp + ghi, EPOCH + timedelta(days=50))
    reports = learner.status["wr"]["regimes"]
    assert reports["nwp"]["lead_bins"]["0-6h"]["calibration_radius_w"] is not None
    assert reports["ghi"]["lead_bins"]["0-6h"]["calibration_target_hours"] == 20
    assert reports["ghi"]["lead_bins"]["0-6h"]["calibration_radius_w"] is None
    row = ghi[-1]
    result = learner.predict("wr", row.features, row.baseline_w, 2000)
    assert result.status == "residual_no_uncertainty" and result.lower_w is None


def test_each_regime_uses_only_its_own_validated_min_max_lead_range():
    nwp, ghi = regimes()
    # Separate issue arms remain prospective and preserve exactly the same AC
    # intervals; gain remains tied to its real baseline and input regime.
    ghi = [replace(row, issued_at=row.start + (row.end - row.start) / 2 - timedelta(hours=lead),
                   features={**row.features, "lead_hours": lead}) for row in ghi for lead in (0.6, 1.3)]
    learner = ResidualLearner().fit(nwp + ghi, EPOCH + timedelta(days=50))
    reports = learner.status["wr"]["regimes"]
    assert reports["ghi"]["lead_bins"]["0-6h"]["supported_lead_min_hours"] == 0.6
    assert reports["ghi"]["lead_bins"]["0-6h"]["supported_lead_max_hours"] == 1.3
    assert reports["nwp"]["lead_bins"]["0-6h"]["supported_lead_min_hours"] == 1.4
    row = ghi[0]
    assert learner.predict("wr", {**row.features, "lead_hours": 1.4}, row.baseline_w, 2000).status == "physics_lead_outside_validated_range"
    assert learner.predict("wr", {**row.features, "lead_hours": 1.0}, row.baseline_w, 2000).status.startswith("residual")


@pytest.mark.parametrize("count,expected_nwp,expected_ghi", [(3, 3, 2), (4, 2, 2), (7, 1, 1)])
async def test_archive_separates_bounded_regime_origins_without_displacement(hass, count, expected_nwp, expected_ghi):
    names = [f"i{index}" for index in range(count)]
    config = SiteConfig(52, 13, "UTC", tuple(StringConfig(f"s{index}", key, 5, 30, 180) for index, key in enumerate(names)), tuple(InverterConfig(key, 5) for key in names))
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    instance = AdaptiveSolarCoordinator(hass, entry, config, AsyncMock())
    start = EPOCH + timedelta(days=1, hours=10)
    for mode, leads in (("nwp", (5.8, 3, 0.5)), ("ghi", (1.4, 1, 0.6))):
        for lead in leads:
            extra = {"ghi_regime": 1, "ghi_nowcast_gain": 0.7, "ghi_observation_age_seconds": 20} if mode == "ghi" else {}
            point = ForecastPoint(start, start + timedelta(hours=1), names[0], 1000, 1000, features={"baseline_w": 1000, "sun_elevation_deg": 45, **extra})
            issue = start + timedelta(minutes=30) - timedelta(hours=lead)
            instance._archive_result(ForecastResult(issue, (point,)))
    assert sum(feature_regime(row["features"]) == "nwp" for row in instance.archive) == expected_nwp
    assert sum(feature_regime(row["features"]) == "ghi" for row in instance.archive) == expected_ghi
    # Another raw NWP issue after an outage cannot erase GHI history.
    saved = [row for row in instance.archive if feature_regime(row["features"]) == "ghi"]
    instance._archive_result(ForecastResult(start, (replace(point, features={"baseline_w": 1000, "sun_elevation_deg": 45}),)))
    assert all(row in instance.archive for row in saved)
    await instance.async_close()


async def test_issue_clipped_output_partial_cell_is_not_an_archived_training_target(hass):
    config = SiteConfig(52, 13, "UTC", (StringConfig("s", "i", 5, 30, 180),), (InverterConfig("i", 5),))
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    instance = AdaptiveSolarCoordinator(hass, entry, config, AsyncMock())
    issued = EPOCH + timedelta(hours=10, minutes=10)
    point = ForecastPoint(issued, issued + timedelta(minutes=50), "i", 1000, 1000,
                          features={"baseline_w": 1000, "sun_elevation_deg": 45, "source_partial_at_issue": 1})
    instance._archive_result(ForecastResult(issued, (point,)))
    assert instance.archive == []
    # Even a previously persisted partial row cannot enter the join later.
    raw = {"issued_at": issued.isoformat(), "start": point.start.isoformat(), "end": point.end.isoformat(), "inverter_id": "i", "baseline_w": 1000, "features": point.features}
    measured = {"start": point.start.isoformat(), "end": point.end.isoformat(), "observed_at": point.end.isoformat(), "inverter_id": "i", "energy_kwh": 1}
    assert join_training([raw], [measured]) == []
    await instance.async_close()
