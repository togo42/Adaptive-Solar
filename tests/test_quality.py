"""HA enum status describes control, coverage and input use, never accuracy."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
import json
from unittest.mock import Mock

from freezegun import freeze_time
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.helpers.translation import async_get_translations
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_solar.coordinator import AdaptiveSolarCoordinator
from custom_components.adaptive_solar.core.engine import ForecastEngine
from custom_components.adaptive_solar.core.learning import Prediction
from custom_components.adaptive_solar.core.models import ForecastPoint, ForecastResult, InverterConfig, SiteConfig, StringConfig, WeatherForecast, WeatherPoint
from custom_components.adaptive_solar.sensor import AdaptiveSolarSensor, FORECAST_SCOPE, QUALITY_OPTIONS

NOW = datetime(2026, 6, 1, 10, tzinfo=UTC)


def sensors(hass, *, irradiance=False, power=False, curtailment=False, two=False, partial=False):
    inverters = tuple(InverterConfig(f"i{index}", 5,
                                    power_entity_id=f"sensor.power{index}" if power else None,
                                    curtailed_entity_id=f"binary_sensor.curtailed{index}" if curtailment else None)
                      for index in range(2 if two else 1))
    config = SiteConfig(52, 13, "UTC", tuple(StringConfig(f"s{index}", inv.id, 5, 30, 180)
                                           for index, inv in enumerate(inverters)), inverters,
                        irradiance_entity_id="sensor.ghi" if irradiance else None)
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    coordinator = AdaptiveSolarCoordinator(hass, entry, config, Mock(errors={}))
    points = tuple(ForecastPoint(NOW + timedelta(hours=hour), NOW + timedelta(hours=hour + 1),
                                inv.id, 1000, 1000) for inv in inverters
                   for hour in range(14) if not (partial and inv.id == inverters[-1].id and hour == 3))
    statuses = {inv.id: "physics;residual_no_uncertainty" for inv in inverters}
    coordinator.data = ForecastResult(NOW, points, {**statuses, "weather:best_match": "available"})
    coordinator.learner_status = {inv.id: {"state": "active"} for inv in inverters}
    coordinator.input_quality = {**{f"curtailment_{inv.id}": "clear" if curtailment else "not_configured"
                                   for inv in inverters},
                                 **({"irradiance": "valid", "irradiance_nowcast": "usable:haurwitz_normalized"}
                                    if irradiance else {}),
                                 **{f"power_{inv.id}": "valid" for inv in inverters if power}}
    return coordinator, entry, AdaptiveSolarSensor(coordinator, entry, None, "quality")


async def test_quality_enum_is_translated_through_real_home_assistant(hass, enable_custom_integrations):
    coordinator, _, sensor = sensors(hass)
    with freeze_time(NOW):
        assert sensor.device_class == SensorDeviceClass.ENUM
        assert sensor.options == list(QUALITY_OPTIONS)
        assert sensor.native_value == "complete"
    translated = await async_get_translations(hass, "de", "entity", {"adaptive_solar"})
    prefix = "component.adaptive_solar.entity.sensor.quality.state."
    assert translated[prefix + "physics"] == "physikalisches Rückfallmodell"
    assert translated[prefix + "curtailed"] == "Abregelung aktiv"
    assert translated[prefix + "mixed"] == "Residualkorrektur teilweise aktiv"
    assert translated[prefix + "complete"] == "Resttag abgedeckt, Residualkorrektur aktiv"
    assert translated[prefix + "partial"] == "Resttag unvollständig abgedeckt"
    assert translated[prefix + "degraded"] == "aktuelle Eingaben eingeschränkt"
    root = Path(__file__).resolve().parents[1] / "custom_components" / "adaptive_solar"
    for path in (root / "strings.json", root / "translations" / "en.json", root / "translations" / "de.json"):
        assert set(json.loads(path.read_text())["entity"]["sensor"]["quality"]["state"]) == set(QUALITY_OPTIONS)
    await coordinator.async_close()


@pytest.mark.parametrize("reading,nowcast", [
    ("ignored:missing_stale_future_or_invalid", "ignored:no_observation"),
    ("valid", "ignored:stale"),
    ("valid", "ignored:conflicting_measurements"),
])
async def test_missing_stale_or_ignored_configured_ghi_is_degraded(hass, reading, nowcast):
    coordinator, _, sensor = sensors(hass, irradiance=True)
    coordinator.input_quality.update(irradiance=reading, irradiance_nowcast=nowcast)
    with freeze_time(NOW):
        assert sensor.native_value == "degraded"
        assert sensor.extra_state_attributes["coverage"] == "complete"
    await coordinator.async_close()


async def test_low_sun_ghi_is_legit_and_unconfigured_optional_inputs_are_not_missing(hass):
    coordinator, _, sensor = sensors(hass, irradiance=True)
    coordinator.input_quality["irradiance_nowcast"] = "ignored:low_sun_or_clear_sky"
    with freeze_time(NOW):
        assert sensor.native_value == "complete"
        coordinator.input_quality["irradiance"] = "ignored:missing_stale_future_or_invalid"
        assert sensor.native_value == "degraded"
    await coordinator.async_close()
    coordinator, _, sensor = sensors(hass)
    coordinator.input_quality = {}
    with freeze_time(NOW):
        assert sensor.native_value == "complete"
        assert sensor.extra_state_attributes["operational_curtailment"] == "not_configured"
    await coordinator.async_close()


async def test_active_curtailment_without_power_preserves_potential_and_marks_every_entity(hass):
    coordinator, entry, quality = sensors(hass, curtailment=True, partial=True)
    coordinator.input_quality["curtailment_i0"] = "active"
    with freeze_time(NOW):
        assert quality.native_value == "curtailed"  # Active flag precedes partial coverage.
        assert quality.extra_state_attributes["coverage"] == "partial"
        for kind in ("power", "remaining", "day", "quality"):
            sensor = AdaptiveSolarSensor(coordinator, entry, "i0", kind, 1 if kind == "day" else 0)
            attrs = sensor.extra_state_attributes
            assert attrs["forecast_scope"] == FORECAST_SCOPE
            assert attrs["operational_curtailment"] == "active"
            assert attrs["operational_curtailment_modelled"] is False
            assert attrs["power_nowcast_control"] == "blocked"
        # A production limit does not replace the available solar potential
        # with a fictional zero delivery forecast.
        assert AdaptiveSolarSensor(coordinator, entry, "i0", "power").native_value == 1000
    await coordinator.async_close()


async def test_unknown_curtailment_is_degraded_but_partial_coverage_has_precedence(hass):
    coordinator, _, sensor = sensors(hass, curtailment=True)
    coordinator.input_quality["curtailment_i0"] = "unknown"
    with freeze_time(NOW):
        assert sensor.native_value == "degraded"
        assert sensor.extra_state_attributes["power_nowcast_control"] == "blocked"
        coordinator.data = replace(coordinator.data, points=coordinator.data.points[:-1])
        assert sensor.native_value == "partial"
    await coordinator.async_close()


async def test_site_partial_and_controls_do_not_poison_unaffected_inverter_scope(hass):
    coordinator, entry, total = sensors(hass, curtailment=True, two=True, partial=True)
    own = AdaptiveSolarSensor(coordinator, entry, "i0", "quality")
    coordinator.input_quality["curtailment_i1"] = "unknown"
    with freeze_time(NOW):
        assert total.native_value == "partial"
        assert own.native_value == "complete"
        coordinator.input_quality["curtailment_i1"] = "active"
        assert total.native_value == "curtailed"
        assert own.native_value == "complete"
    await coordinator.async_close()


async def test_untrained_or_rejected_daylight_ml_reports_physics_without_accuracy_claim(hass):
    coordinator, _, sensor = sensors(hass)
    coordinator.learner_status = {"i0": {"state": "insufficient_history"}}
    coordinator.data = replace(coordinator.data, model_status={"i0": "physics_insufficient_history"})
    with freeze_time(NOW):
        assert sensor.native_value == "physics"
        assert sensor.extra_state_attributes["coverage"] == "complete"
        coordinator.learner_status = {"i0": {"state": "active"}}
        coordinator.data = replace(coordinator.data, model_status={"i0": "physics_lead_rejected_validation;residual_no_uncertainty"})
        assert sensor.native_value == "mixed"
        coordinator.data = replace(coordinator.data, model_status={"i0": "physics"})
        assert sensor.native_value == "physics"
    await coordinator.async_close()


async def test_ignored_configured_power_precedes_model_fallback(hass):
    coordinator, _, sensor = sensors(hass, power=True)
    coordinator.input_quality["power_i0"] = "missing_stale_or_invalid"
    coordinator.learner_status = {"i0": {"state": "insufficient_history"}}
    with freeze_time(NOW):
        assert sensor.native_value == "degraded"
    await coordinator.async_close()


@pytest.mark.parametrize("application,expected", [("near", "mixed"), ("none", "physics"), ("all", "complete")])
async def test_published_near_residuals_and_far_fallback_have_honest_enum(hass, application, expected):
    coordinator, _, sensor = sensors(hass)

    class Learner:
        def predict(self, inverter_id, features, baseline_w, cap_w):
            if application == "all" or application == "near" and features["lead_hours"] < 6:
                return Prediction(baseline_w * 0.8, status="residual_no_uncertainty")
            return Prediction(baseline_w, status="physics_lead_insufficient_validation")

    forecast = WeatherForecast("best_match", NOW, tuple(
        WeatherPoint(NOW + timedelta(hours=h), NOW + timedelta(hours=h + 1),
                     600, 480, 180, 20, 2, 20) for h in range(168)))
    coordinator.data = ForecastEngine(coordinator.site).forecast((forecast,), NOW, learner=Learner())
    coordinator.learner_status = {"i0": {"state": "active", "regimes": {
        "nwp": {"state": "active", "lead_bins": {
            "0-6h": {"state": "active", "supported_lead_min_hours": 0.5,
                     "supported_lead_max_hours": 5.5},
            "96h+": {"state": "insufficient_validation"}}},
        "ghi": {"state": "insufficient_history"}}}}
    with freeze_time(NOW):
        assert sensor.native_value == expected
        attrs = sensor.extra_state_attributes
        horizon = attrs["learning_horizon"]
        assert attrs["coverage_scope"] == "remaining_local_day"
        assert horizon["scope"] == "published_forecast_horizon"
        assert horizon["start"] == NOW.isoformat()
        assert horizon["end"] == (NOW + timedelta(days=7)).replace(hour=0).isoformat()
        assert horizon["support_evidence"] == "internal_chronological_validation_not_future_accuracy"
        support = horizon["inverters"]["i0"]["validated_lead_support"]
        assert support["nwp"]["lead_ranges"]["0-6h"] == {"min_hours": 0.5, "max_hours": 5.5}
        assert support["ghi"]["state"] == "insufficient_history"
        if application == "near":
            assert horizon["application"] == "mixed"
            assert any(p.power_w < p.baseline_w for p in coordinator.data.points
                       if p.features["lead_hours"] < 6)
            assert any(p.baseline_w > 0 and p.power_w == p.baseline_w for p in coordinator.data.points
                       if p.features["lead_hours"] > 96)
        if application == "all":
            # Real engine night cells publish plain physics, never residuals.
            # They do not cancel active daytime corrections or imply a gap.
            assert "physics" in horizon["inverters"]["i0"]["published_statuses"]
            assert horizon["application"] == "residual"
    await coordinator.async_close()


async def test_opposite_regime_report_does_not_hide_actual_residual_and_stage_scope(hass):
    coordinator, entry, total = sensors(hass, two=True)
    coordinator.data = replace(coordinator.data, model_status={
        "i0": "physics_night;residual_no_uncertainty", "i1": "physics_regime_insufficient_history"})
    coordinator.learner_status["i0"] = {"state": "active", "regimes": {
        "nwp": {"state": "insufficient_history"}, "ghi": {"state": "active"}}}
    own = AdaptiveSolarSensor(coordinator, entry, "i0", "quality")
    other = AdaptiveSolarSensor(coordinator, entry, "i1", "quality")
    with freeze_time(NOW):
        assert total.native_value == "mixed"
        assert own.native_value == "complete"
        assert other.native_value == "physics"
        assert set(own.extra_state_attributes["learning_horizon"]["inverters"]) == {"i0"}
    await coordinator.async_close()


async def test_night_only_is_physics_and_remaining_scope_changes_at_local_midnight(hass):
    coordinator, _, sensor = sensors(hass)
    night = datetime(2026, 6, 1, 23, tzinfo=UTC)
    coordinator.data = ForecastResult(night, tuple(
        ForecastPoint(night + timedelta(hours=h), night + timedelta(hours=h + 1),
                      "i0", 0, 0, features={"sun_elevation_deg": -15}) for h in range(25)),
        {"i0": "physics;physics_night"})
    ends = []
    for instant in [night + timedelta(minutes=55), night + timedelta(hours=1, minutes=5)]:
        with freeze_time(instant):
            assert sensor.native_value == "physics"
            attrs = sensor.extra_state_attributes
            assert attrs["coverage"] == "complete"
            assert attrs["learning_horizon"]["application"] == "physics"
            assert attrs["learning_horizon"]["start"] == night.isoformat()
            assert attrs["coverage_start"] == instant.isoformat()
            ends.append(datetime.fromisoformat(attrs["coverage_end"]))
    assert ends[1] - ends[0] == timedelta(days=1)
    await coordinator.async_close()


async def test_missing_physics_member_diagnostics_do_not_degrade_valid_remaining_output(hass):
    coordinator, _, sensor = sensors(hass)
    coordinator.data = replace(coordinator.data, model_status={
        "i0": "residual_no_uncertainty", "physics:model:interval": "unavailable:nonfinite_string_power"})
    with freeze_time(NOW):
        assert sensor.native_value == "complete"
        assert sensor.extra_state_attributes["learning_horizon"]["application"] == "residual"
        assert sensor.extra_state_attributes["model_status"]["physics:model:interval"].startswith("unavailable:")
    await coordinator.async_close()


async def test_actual_future_physics_gap_is_diagnostic_without_changing_today_quality(hass):
    coordinator, _, sensor = sensors(hass)
    tomorrow = NOW.replace(hour=0) + timedelta(days=1)
    future = tuple(ForecastPoint(tomorrow + timedelta(hours=h), tomorrow + timedelta(hours=h + 1),
                                 "i0", 1000, 1000) for h in range(24) if h != 4)
    key = f"physics:best_match:{(tomorrow + timedelta(hours=4)).isoformat()}/{(tomorrow + timedelta(hours=5)).isoformat()}"
    coordinator.data = replace(coordinator.data, points=(*coordinator.data.points, *future),
                               model_status={"i0": "residual_no_uncertainty", key: "unavailable:nonfinite_dc_power"})
    with freeze_time(NOW):
        assert sensor.native_value == "complete"
        attrs = sensor.extra_state_attributes
        assert attrs["coverage"] == "complete"
        assert attrs["input_quality_scope"] == "current_issue_observations_and_controls"
        assert attrs["model_status_scope"] == "published_forecast_horizon"
        assert key in attrs["model_status"]
        assert coordinator.data.energy_kwh(tomorrow, tomorrow + timedelta(days=1), "i0") is None
    await coordinator.async_close()


async def test_failed_additional_provider_is_retained_without_degrading_valid_today(hass):
    coordinator, _, sensor = sensors(hass)
    coordinator.site = replace(coordinator.site, weather_models=("best_match", "icon_d2"))
    coordinator.client.errors = {"icon_d2": "provider_unavailable"}
    coordinator.data = replace(coordinator.data, model_status={
        "i0": "residual_no_uncertainty", "weather:best_match": "available", "weather:icon_d2": "unavailable"})
    with freeze_time(NOW):
        assert sensor.native_value == "complete"
        attrs = sensor.extra_state_attributes
        assert attrs["weather_errors"] == {"icon_d2": "provider_unavailable"}
        assert attrs["weather_errors_scope"] == "latest_provider_fetches_diagnostic_only"
    await coordinator.async_close()


async def test_actual_today_physics_gap_remains_partial(hass):
    coordinator, _, sensor = sensors(hass, partial=True)
    coordinator.data = replace(coordinator.data, model_status={
        "i0": "residual_no_uncertainty", "physics:model:current_interval": "unavailable:nonfinite_dc_power"})
    with freeze_time(NOW):
        assert sensor.native_value == "partial"
        assert sensor.extra_state_attributes["coverage"] == "partial"
    await coordinator.async_close()


async def test_beam_shade_diagnostics_in_quality_and_entry_diagnostics(hass):
    from unittest.mock import AsyncMock
    from custom_components.adaptive_solar.diagnostics import async_get_config_entry_diagnostics
    from custom_components.adaptive_solar.core.physics import solar_position

    coordinator, entry, sensor = sensors(hass, irradiance=True, power=True)
    entry.runtime_data = coordinator
    sun = solar_position(coordinator.site, NOW)
    for idx in range(5):
        coordinator.shading.record("i0", sun.azimuth_deg, sun.elevation_deg, NOW - timedelta(minutes=15 * idx), 0.65)
    forecast = WeatherForecast("best_match", NOW, tuple(
        WeatherPoint(NOW + timedelta(hours=h), NOW + timedelta(hours=h + 1), 700, 700, 100, 20, 2, 10)
        for h in range(14)
    ))
    coordinator.client = AsyncMock()
    coordinator.client.errors = {}
    coordinator.client.async_forecasts.return_value = (forecast,)
    with freeze_time(NOW):
        hass.states.async_set("sensor.ghi", "100", {"unit_of_measurement": "W/m²"})
        hass.states.async_set("sensor.power0", "4950", {"unit_of_measurement": "W"})
        await coordinator._async_update_data()
        attrs = sensor.extra_state_attributes
        diag = await async_get_config_entry_diagnostics(hass, entry)
        shade = attrs["learning"]["i0"]["beam_shade"]
        assert diag["learning"]["i0"]["beam_shade"] == shade
        assert shade["azimuth_bin_deg"] is not None
        assert shade["elevation_bin_deg"] is not None
        assert shade["transmittance"] == pytest.approx(0.65)
        assert shade["samples"] == 5
        assert shade["released"] is True
        assert shade["filled_bins"] == 1
        assert {"at_cap", "low_clearness"} <= set(shade["last_rejection"].split(";"))
    # Night without sun shows factor 1, unreleased and no invented bin.
    night = NOW.replace(hour=23)
    night_fc = WeatherForecast("best_match", night, (
        WeatherPoint(night, night + timedelta(hours=1), 0, 0, 0, 15, 2, 0),
    ))
    coordinator.client.async_forecasts.return_value = (night_fc,)
    with freeze_time(night):
        await coordinator._async_update_data()
        night_shade = coordinator.learner_status["i0"]["beam_shade"]
        assert night_shade["azimuth_bin_deg"] is None
        assert night_shade["elevation_bin_deg"] is None
        assert night_shade["transmittance"] == 1.0
        assert night_shade["samples"] == 0
        assert night_shade["released"] is False
        assert night_shade["filled_bins"] == 1
    await coordinator.async_close()
