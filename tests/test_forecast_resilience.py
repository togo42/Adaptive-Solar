"""Optional learning and bounded weather failures preserve valid physics only."""
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from freezegun import freeze_time
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_solar.coordinator import AdaptiveSolarCoordinator
from custom_components.adaptive_solar.core.learning import ResidualLearner
from custom_components.adaptive_solar.core.models import InverterConfig, SiteConfig, StringConfig
from custom_components.adaptive_solar.weather import OpenMeteoClient, UNITS, VARIABLES, WeatherError, parse_forecast

NOW = datetime(2026, 6, 1, 10, tzinfo=UTC)


def site(models=("best_match",)):
    return SiteConfig(52, 13, "Europe/Berlin", (StringConfig("s", "i", 5, 30, 180),),
                      (InverterConfig("i", 5),), weather_models=models)


def payload(count=50):
    return {"hourly_units": dict(UNITS), "hourly": {
        "time": [(NOW + timedelta(hours=h - 1)).timestamp() for h in range(count)],
        **{key: [value] * count for key, value in zip(VARIABLES, [500, 600, 100, 20, 3, 40], strict=True)}}}


def client_for(config):
    response = AsyncMock()
    response.raise_for_status = Mock()
    response.json.return_value = payload()
    session = Mock()
    session.get.return_value.__aenter__ = AsyncMock(return_value=response)
    session.get.return_value.__aexit__ = AsyncMock(return_value=False)
    return OpenMeteoClient(session, config), session


async def test_fit_failure_preserves_physics_and_retries_atomically(hass, monkeypatch):
    config = site()
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    provider = AsyncMock()
    provider.async_forecasts.return_value = (parse_forecast(payload(), "best_match", NOW),)
    coordinator = AdaptiveSolarCoordinator(hass, entry, config, provider)
    original_fit = ResidualLearner.fit
    fit = Mock(side_effect=RuntimeError("optional model failure"))
    monkeypatch.setattr(ResidualLearner, "fit", fit)
    with freeze_time(NOW):
        result = await coordinator._async_update_data()
        assert result.points and all(p.power_w == p.baseline_w for p in result.points)
        assert coordinator._learner is None and coordinator._fit_signature is None
        assert coordinator.learner_status["i"]["state"] == "fit_failed"
        assert coordinator.resource_diagnostics["fit_error"] == "RuntimeError"
        assert coordinator.resource_diagnostics["fit_failure_count"] == 1
        policy = coordinator.learner_status["i"]["training_quality"]["policy"]
        assert policy["counter_pending_wait_seconds"] == 900
        assert policy["counter_plausibility_window_seconds"] == 60
        assert policy["max_internal_gap_seconds"] == 1
        assert policy["max_internal_gap_seconds_per_target_hour"] == 5
        assert policy["gap_energy_and_duration_filled"] is False
        monkeypatch.setattr(ResidualLearner, "fit", original_fit)
        recovered = await coordinator._async_update_data()
        assert recovered.points and coordinator._learner is not None
        assert coordinator.resource_diagnostics["fit_count"] == 2
        assert coordinator.resource_diagnostics["fit_error"] is None
        assert coordinator.resource_diagnostics["last_fit_success_at"] == NOW.isoformat()
    await coordinator.async_close()


async def test_refit_failure_never_reuses_old_learner(hass, monkeypatch):
    config = site()
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    provider = AsyncMock()
    provider.async_forecasts.return_value = (parse_forecast(payload(), "best_match", NOW),)
    coordinator = AdaptiveSolarCoordinator(hass, entry, config, provider)
    with freeze_time(NOW):
        await coordinator._async_update_data()
        previous = coordinator._learner
        previous.predict = Mock(side_effect=AssertionError("old learner must not be consulted"))
        coordinator._history_revision += 1
        monkeypatch.setattr(ResidualLearner, "fit", Mock(side_effect=ValueError("changed data rejected")))
        result = await coordinator._async_update_data()
        assert result.points and coordinator._learner is None
        previous.predict.assert_not_called()
    await coordinator.async_close()


async def test_physics_failure_is_not_swallowed_and_does_not_publish_candidate(hass, monkeypatch):
    config = site()
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    provider = AsyncMock()
    provider.async_forecasts.return_value = (parse_forecast(payload(), "best_match", NOW),)
    coordinator = AdaptiveSolarCoordinator(hass, entry, config, provider)
    monkeypatch.setattr(coordinator.engine, "forecast", Mock(side_effect=RuntimeError("mandatory physics failed")))
    with freeze_time(NOW), pytest.raises(RuntimeError, match="mandatory physics"):
        await coordinator._async_update_data()
    assert coordinator._learner is None
    assert coordinator.resource_diagnostics["fit_count"] == 0
    await coordinator.async_close()


async def test_weather_cache_expiry_timeout_and_recovery_preserve_original_receipt():
    client, session = client_for(site())
    with freeze_time(NOW):
        first = await client.async_forecasts(NOW)
        cached = await client.async_forecasts(NOW + timedelta(minutes=59))
    assert cached[0] is first[0] and session.get.call_count == 1
    assert client.diagnostics["best_match"]["cache_state"] == "fresh_cache"
    session.get.return_value.__aenter__.side_effect = TimeoutError
    stale = await client.async_forecasts(NOW + timedelta(hours=1))
    assert stale[0] is first[0] and stale[0].issued_at == NOW
    assert client.errors and client.diagnostics["best_match"]["cache_state"] == "stale_if_error"
    assert client.diagnostics["best_match"]["age_seconds"] == 3600
    session.get.return_value.__aenter__.side_effect = None
    with freeze_time(NOW + timedelta(hours=2)):
        recovered = await client.async_forecasts(NOW + timedelta(hours=2))
    assert recovered[0].issued_at == NOW + timedelta(hours=2)
    assert client.errors == {} and client.diagnostics["best_match"]["cache_state"] == "fresh_fetch"


@pytest.mark.parametrize("offset", [timedelta(hours=12, seconds=1), timedelta(seconds=-1)])
async def test_stale_cache_rejects_overage_and_future_receipts(offset):
    client, session = client_for(site())
    with freeze_time(NOW):
        await client.async_forecasts(NOW)
    session.get.return_value.__aenter__.side_effect = TimeoutError
    with pytest.raises(WeatherError, match="No weather model"):
        await client.async_forecasts(NOW + offset)
    assert client.diagnostics["best_match"]["cache_state"] == "unavailable"


async def test_stale_cache_requires_future_support_and_configured_age_limit():
    client, session = client_for(site())
    client.max_stale_age = timedelta(hours=2)
    with freeze_time(NOW):
        await client.async_forecasts(NOW)
    session.get.return_value.__aenter__.side_effect = TimeoutError
    assert (await client.async_forecasts(NOW + timedelta(hours=2)))[0].issued_at == NOW
    with pytest.raises(WeatherError):
        await client.async_forecasts(NOW + timedelta(hours=2, seconds=1))
    client._cache["best_match"] = parse_forecast(payload(count=2), "best_match", NOW)
    with pytest.raises(WeatherError):
        await client.async_forecasts(NOW + timedelta(hours=1))
    with pytest.raises(ValueError, match="age limit"):
        OpenMeteoClient(session, site(), max_stale_age=timedelta(hours=13))


async def test_single_member_failure_and_total_failure_are_explicit():
    client, session = client_for(site(("best_match", "icon_d2")))
    session.get.return_value.__aenter__.side_effect = [TimeoutError, session.get.return_value.__aenter__.return_value]
    with freeze_time(NOW):
        forecasts = await client.async_forecasts(NOW)
    assert [f.model for f in forecasts] == ["icon_d2"]
    assert set(client.errors) == {"best_match"}
    session.get.return_value.__aenter__.side_effect = TimeoutError
    with pytest.raises(WeatherError):
        await client.async_forecasts(NOW + timedelta(hours=13))
    assert set(client.errors) == {"best_match", "icon_d2"}


def test_ambient_interval_diagnostics_retain_gaps_and_bound_examples():
    data = payload()
    data["hourly"]["temperature_2m"][2:30] = [None] * 28
    diagnostics = {}
    result = parse_forecast(data, "best_match", NOW, site(), diagnostics)
    assert diagnostics["interval_rejection_reasons"]["invalid_ambient_endpoint"] == 28
    assert diagnostics["interval_rejection_reasons"]["invalid_previous_ambient_endpoint"] == 28
    assert len(diagnostics["interval_rejection_examples"]) == 8
    assert not any(p.start <= NOW + timedelta(hours=10) < p.end for p in result.points)


async def test_fit_reuse_requires_same_joined_inputs_and_receipt_availability(hass):
    config = site()
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    provider = AsyncMock()
    provider.async_forecasts.return_value = (parse_forecast(payload(), "best_match", NOW),)
    coordinator = AdaptiveSolarCoordinator(hass, entry, config, provider)
    coordinator._archive_result = Mock()  # Keep history fixed to isolate as_of changes.
    start, end = NOW - timedelta(hours=2), NOW - timedelta(hours=1)
    coordinator.archive = [{"issued_at": (start - timedelta(hours=1)).isoformat(),
        "start": start.isoformat(), "end": end.isoformat(), "inverter_id": "i", "baseline_w": 2000,
        "features": {"baseline_w": 2000, "sun_elevation_deg": 45}}]
    coordinator.intervals = [{"inverter_id": "i", "start": start.isoformat(), "end": end.isoformat(),
        "observed_at": (NOW + timedelta(minutes=1)).isoformat(), "energy_kwh": 1}]
    with freeze_time(NOW):
        await coordinator._async_update_data()
        first = coordinator._learner
        shadow_cutoff = coordinator.bias_shadow_status["fit_evaluated_at"]
        await coordinator._async_update_data()
        assert coordinator._learner is first
        assert coordinator.resource_diagnostics["fit_reuse_count"] == 1
    revision = coordinator._history_revision
    with freeze_time(NOW + timedelta(minutes=2)):
        await coordinator._async_update_data()
        assert coordinator._history_revision == revision
        assert coordinator._learner is not first
        assert coordinator.bias_shadow_status["fit_evaluated_at"] != shadow_cutoff
        assert coordinator.resource_diagnostics["accepted_unique_measured_hours"] == {"i": 1}
        assert coordinator.resource_diagnostics["fit_count"] == 2
        assert all(coordinator.resource_diagnostics[key] >= 0
                   for key in ("join_seconds", "fit_seconds", "forecast_seconds"))
    await coordinator.async_close()


@pytest.mark.parametrize("month,day,hours", [(3, 29, 23), (10, 25, 25)])
def test_weather_day_coverage_uses_dst_seconds(month, day, hours):
    from zoneinfo import ZoneInfo

    zone = ZoneInfo("Europe/Berlin")
    start = datetime(2026, month, day, tzinfo=zone).astimezone(UTC)
    data = payload(count=hours + 1)
    data["hourly"]["time"] = [(start + timedelta(hours=h)).timestamp() for h in range(hours + 1)]
    forecast = parse_forecast(data, "best_match", start)
    client, _ = client_for(site())
    client._cache_diagnostics("best_match", forecast, start, "fresh_fetch")
    coverage = client.diagnostics["best_match"]["day_coverage"][start.astimezone(zone).date().isoformat()]
    assert coverage == {"required_seconds": hours * 3600, "supported_seconds": hours * 3600, "complete": True}


async def test_stale_weather_and_failed_fit_degrade_quality_and_expose_diagnostics(hass):
    from custom_components.adaptive_solar.diagnostics import async_get_config_entry_diagnostics
    from custom_components.adaptive_solar.sensor import AdaptiveSolarSensor

    config = site()
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    provider, session = client_for(config)
    coordinator = AdaptiveSolarCoordinator(hass, entry, config, provider)
    entry.runtime_data = coordinator
    with freeze_time(NOW):
        coordinator.async_set_updated_data(await coordinator._async_update_data())
        sensor = AdaptiveSolarSensor(coordinator, entry, "i", "quality")
        assert sensor.native_value == "physics"
    session.get.return_value.__aenter__.side_effect = TimeoutError
    with freeze_time(NOW + timedelta(hours=1)):
        coordinator.async_set_updated_data(await coordinator._async_update_data())
        assert sensor.native_value == "degraded"
        assert sensor.extra_state_attributes["weather_diagnostics"]["best_match"]["fetch_error"] == "TimeoutError"
        diagnostics = await async_get_config_entry_diagnostics(hass, entry)
        assert diagnostics["resources"]["fit_count"] > 0
        assert diagnostics["weather_diagnostics"]["best_match"]["original_issued_at"] == NOW.isoformat()
        provider.diagnostics["best_match"]["cache_state"] = "fresh_fetch"
        coordinator.resource_diagnostics["fit_error"] = "RuntimeError"
        assert sensor.native_value == "degraded"
    await coordinator.async_close()
