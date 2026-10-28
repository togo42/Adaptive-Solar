"""Synthetic chronology and shadow-only behavior, not accuracy evidence."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from freezegun import freeze_time
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_solar.coordinator import AdaptiveSolarCoordinator
from custom_components.adaptive_solar.core.early_bias import EarlyBiasShadow
from custom_components.adaptive_solar.core.learning import FEATURE_NAMES
from custom_components.adaptive_solar.core.models import (
    ForecastPoint, ForecastResult, InverterConfig, SiteConfig, StringConfig, TrainingSample,
)

EPOCH = datetime(2026, 6, 1, tzinfo=UTC)
CAP = 5000


def rows(count=14, ratio=0.9, *, regime=0, lead=2):
    result = []
    for day in range(count):
        for hour in range(4):
            start = EPOCH + timedelta(days=day, hours=10 + hour)
            features = dict.fromkeys(FEATURE_NAMES, 0.0)
            features.update(baseline_w=1000, sun_elevation_deg=35, sun_azimuth_cos=1,
                            temperature_c=20, wind_m_s=2, cloud_cover_pct=10,
                            lead_hours=lead, ghi_regime=regime, ghi_nowcast_gain=1,
                            output_cap_w=CAP, beam_shade_factor=1)
            result.append(TrainingSample(start - timedelta(hours=lead - 0.5), start,
                start + timedelta(hours=1), start + timedelta(hours=1, minutes=1),
                "i", 1000, 1000 * ratio, features))
    return result


def report(learner, regime="nwp", name="0-6h"):
    return learner.status["i"]["regimes"][regime][name]


def test_regularized_gain_requires_chronological_history_and_stays_shadow():
    samples = rows()
    learner = EarlyBiasShadow(output_caps={"i": CAP}).fit(samples, EPOCH + timedelta(days=15))
    state = report(learner)
    assert state["state"] == "shadow_ready"
    assert state["operational_use"] is False
    assert state["train_end"] < state["validation_start"]
    assert 0.9 < state["gain"] < 1
    prediction = learner.predict("i", samples[0].features, 1000, CAP)
    assert prediction.status == "shadow_bias_candidate"
    assert prediction.power_w == pytest.approx(1000 * state["gain"])
    assert prediction.lower_w is None and prediction.upper_w is None
    short = EarlyBiasShadow(output_caps={"i": CAP}).fit(rows(count=13), EPOCH + timedelta(days=15))
    assert report(short)["state"] == "insufficient_history"
    duplicate = EarlyBiasShadow(output_caps={"i": CAP}).fit(rows(count=3) * 20, EPOCH + timedelta(days=15))
    assert report(duplicate)["unique_target_hours"] == 12
    assert report(duplicate)["state"] == "insufficient_history"


def test_validation_labels_never_fit_gain_and_future_labels_never_enter():
    samples = rows()
    first = EarlyBiasShadow(output_caps={"i": CAP}).fit(samples, EPOCH + timedelta(days=15))
    validation_start = datetime.fromisoformat(report(first)["validation_start"]).replace(tzinfo=UTC)
    revised = [replace(row, actual_w=1000) if row.start >= validation_start else row for row in samples]
    second = EarlyBiasShadow(output_caps={"i": CAP}).fit(revised, EPOCH + timedelta(days=15))
    assert report(first)["gain"] == report(second)["gain"]
    assert report(second)["state"] == "rejected_validation"
    future = [replace(row, observed_at=EPOCH + timedelta(days=30), actual_w=4000) for row in rows(count=20)]
    third = EarlyBiasShadow(output_caps={"i": CAP}).fit(samples + future, EPOCH + timedelta(days=15))
    assert report(third) == report(first)


def test_causal_cutoff_rejects_labels_received_after_first_validation_issue():
    samples = rows()
    # All earlier labels become available only after the first validation issue.
    late = [replace(row, observed_at=EPOCH + timedelta(days=14)) for row in samples]
    learner = EarlyBiasShadow(output_caps={"i": CAP}).fit(late, EPOCH + timedelta(days=15))
    assert report(learner)["state"] == "insufficient_causal_training"


def test_gain_is_regularized_and_candidates_obey_the_output_cap():
    samples = [replace(row, baseline_w=4500, actual_w=5400,
                       features={**row.features, "baseline_w": 4500}) for row in rows()]
    learner = EarlyBiasShadow(output_caps={"i": CAP}).fit(samples, EPOCH + timedelta(days=15))
    assert report(learner)["state"] == "shadow_ready"
    assert 1 < report(learner)["gain"] < 1.2
    assert learner.predict("i", samples[0].features, 4500, CAP).power_w == CAP
    weak = [replace(row, baseline_w=200, actual_w=180,
                    features={**row.features, "baseline_w": 200}) for row in rows()]
    learner.fit(weak, EPOCH + timedelta(days=15))
    assert learner.status == {}


@pytest.mark.parametrize("changed", ["regime", "lead", "shade", "cap"])
def test_prediction_does_not_extrapolate_between_independent_support(changed):
    samples = rows()
    learner = EarlyBiasShadow(output_caps={"i": CAP}).fit(samples, EPOCH + timedelta(days=15))
    features, cap = dict(samples[0].features), CAP
    if changed == "regime":
        features["ghi_regime"] = 1
    elif changed == "lead":
        features["lead_hours"] = 4
    elif changed == "shade":
        features["beam_shade_factor"] = 0.8
    else:
        cap = 4000
    assert learner.predict("i", features, 1000, cap).status == "physics_shadow_unavailable"


def test_each_regime_and_lead_bin_requires_its_own_history():
    samples = rows() + rows(count=13, regime=1) + rows(count=13, lead=12)
    learner = EarlyBiasShadow(output_caps={"i": CAP}).fit(samples, EPOCH + timedelta(days=15))
    assert report(learner)["state"] == "shadow_ready"
    assert report(learner, "ghi")["state"] == "insufficient_history"
    assert report(learner, name="6-24h")["state"] == "insufficient_history"


def test_conflicting_duplicate_labels_and_incompatible_shade_phase_fail_closed():
    samples = rows()
    conflict = [replace(row, actual_w=800) for row in samples]
    learner = EarlyBiasShadow(output_caps={"i": CAP}).fit(samples + conflict, EPOCH + timedelta(days=15))
    assert learner.status == {}
    changed = [replace(row, features={**row.features, "beam_shade_factor": 0.7})
               if row.start >= EPOCH + timedelta(days=11) else row for row in samples]
    learner.fit(changed, EPOCH + timedelta(days=15))
    assert report(learner)["state"] == "incompatible_shade_support"


async def test_coordinator_shadow_never_changes_published_points_and_is_atomic(hass, monkeypatch):
    config = SiteConfig(52, 13, "UTC", (StringConfig("s", "i", 5, 30, 180),), (InverterConfig("i", 5),))
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    coordinator = AdaptiveSolarCoordinator(hass, entry, config, AsyncMock())
    coordinator.client.async_forecasts.return_value = ()
    samples = rows()
    point = ForecastPoint(EPOCH + timedelta(days=15, hours=10), EPOCH + timedelta(days=15, hours=11),
                          "i", 1000, 1050, features=samples[0].features)
    published = ForecastResult(point.start - timedelta(hours=1.5), (point,))
    monkeypatch.setattr("custom_components.adaptive_solar.coordinator.join_training", Mock(return_value=samples))
    monkeypatch.setattr(coordinator.engine, "forecast", Mock(return_value=published))
    with freeze_time(published.issued_at):
        output = await coordinator._async_update_data()
        assert output is published and output.points[0].power_w == 1050
        assert len(coordinator._shadow_archive_pending) == 1
        assert coordinator._shadow_archive_pending[0].power_w < 1000
        assert coordinator.bias_shadow_status["operational_use"] is False
        first = coordinator._bias_shadow
        await coordinator._async_update_data()
        assert coordinator._bias_shadow is first
        coordinator._bias_fit_signature = None
        monkeypatch.setattr(EarlyBiasShadow, "fit", Mock(side_effect=RuntimeError("optional shadow failed")))
        assert await coordinator._async_update_data() is published
        assert coordinator._bias_shadow is None and coordinator._shadow_archive_pending == ()
        assert coordinator.bias_shadow_status["fit_error"] == "RuntimeError"
    await coordinator.async_close()
