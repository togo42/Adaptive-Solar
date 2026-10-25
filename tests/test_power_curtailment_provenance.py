"""A cleared control flag cannot rehabilitate power from its blocked phase."""
from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock

from freezegun import freeze_time
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_solar.coordinator import AdaptiveSolarCoordinator
from custom_components.adaptive_solar.core.models import WeatherForecast, WeatherPoint
from tests.test_coordinator import NOW, site


@pytest.mark.parametrize("previous", ["on", "unknown", "unavailable", None])
@pytest.mark.parametrize("start_late", [False, True])
async def test_power_before_control_clear_is_blocked_until_a_real_report(hass, previous, start_late):
    config = site()
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    coordinator = AdaptiveSolarCoordinator(hass, entry, config, AsyncMock())
    units = {"unit_of_measurement": "W"}
    with freeze_time(NOW):
        if previous is not None:
            hass.states.async_set("binary_sensor.curtailed", previous)
        if not start_late:
            coordinator.async_start_tracking()
        hass.states.async_set("sensor.power", "200", units)
        await hass.async_block_till_done()
    clear = NOW + timedelta(minutes=5)
    with freeze_time(clear):
        hass.states.async_set("binary_sensor.curtailed", "off")
        await hass.async_block_till_done()
        if start_late:
            coordinator.async_start_tracking()
    issued = clear + timedelta(minutes=1)
    weather = (WeatherForecast("best_match", NOW, tuple(
        WeatherPoint(NOW + timedelta(hours=h), NOW + timedelta(hours=h + 1), 500, 600, 100, 20, 2, 30)
        for h in range(4))),)
    observations = coordinator._observations(issued)
    assert coordinator.input_quality["curtailment_i"] == "clear"
    assert coordinator.input_quality["power_i"] == "ignored:predates_curtailment_clear"
    power = [value for value in observations if value.power_w is not None]
    assert not power or all(value.curtailed for value in power)
    baseline = coordinator.engine.forecast(weather, issued)
    assert coordinator.engine.forecast(weather, issued, observations).points == baseline.points
    # This repeated unchanged value is a genuine HA report, not a poll. It
    # advances last_reported while preserving last_updated from the old phase.
    reported = issued + timedelta(minutes=1)
    with freeze_time(reported):
        hass.states.async_set("sensor.power", "200", units)
        await hass.async_block_till_done()
    assert hass.states.get("sensor.power").last_updated == NOW
    observations = coordinator._observations(reported)
    power = next(value for value in observations if value.power_w is not None)
    assert power.time == reported and not power.curtailed
    assert coordinator.engine.forecast(weather, reported, observations).points != coordinator.engine.forecast(weather, reported).points
    assert coordinator.intervals == []
    await coordinator.async_close()


async def test_unbound_control_keeps_optional_unconstrained_power_semantics(hass):
    config = site()
    config = replace(config, inverters=(replace(config.inverters[0], curtailed_entity_id=None),))
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    coordinator = AdaptiveSolarCoordinator(hass, entry, config, AsyncMock())
    with freeze_time(NOW):
        hass.states.async_set("sensor.power", "200", {"unit_of_measurement": "W"})
    power = next(value for value in coordinator._observations(NOW + timedelta(minutes=1)) if value.power_w is not None)
    assert power.time == NOW and not power.curtailed
    await coordinator.async_close()
