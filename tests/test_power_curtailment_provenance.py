"""A cleared control flag cannot rehabilitate power from its blocked phase."""
from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock

from freezegun import freeze_time
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_solar.coordinator import AdaptiveSolarCoordinator
from custom_components.adaptive_solar.core.models import InverterConfig, WeatherForecast, WeatherPoint
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


@pytest.mark.parametrize("output_type", ["ac", "dc"])
@pytest.mark.parametrize("start_late", [False, True])
async def test_restored_control_blocks_labels_and_power_until_genuine_recovery(hass, output_type, start_late):
    config = site()
    inv = InverterConfig("i", max_output_kw=5, output_type=output_type,
                         energy_entity_id="sensor.energy", power_entity_id="sensor.power",
                         curtailed_entity_id="binary_sensor.curtailed")
    config = replace(config, inverters=(inv,))
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    coordinator = AdaptiveSolarCoordinator(hass, entry, config, AsyncMock())
    power_unit = {"unit_of_measurement": "W"}
    energy_unit = {"unit_of_measurement": "kWh"}
    with freeze_time(NOW):
        hass.states.async_set("binary_sensor.curtailed", "off")
        coordinator.async_start_tracking()
        hass.states.async_set("sensor.energy", "10", energy_unit)
        await hass.async_block_till_done()
    with freeze_time(NOW + timedelta(minutes=1)):
        hass.states.async_set("binary_sensor.curtailed", "off", {"restored": True})
        await hass.async_block_till_done()
        if start_late:
            await coordinator.async_close()
            coordinator = AdaptiveSolarCoordinator(hass, entry, config, AsyncMock())
            coordinator.async_start_tracking()
        hass.states.async_set("sensor.energy", "10.01", energy_unit)
        hass.states.async_set("sensor.power", "200", power_unit)
        await hass.async_block_till_done()
        observations = coordinator._observations(NOW + timedelta(minutes=1))
        assert not coordinator._curtailment_safe(inv)
        assert coordinator.input_quality["curtailment_i"] == "unknown"
        assert all(obs.curtailed for obs in observations if obs.power_w is not None)
        assert any(obs.curtailed and obs.power_w is None for obs in observations)
        assert coordinator.intervals == []
    clear = NOW + timedelta(minutes=2)
    with freeze_time(clear):
        hass.states.async_set("binary_sensor.curtailed", "off")
        await hass.async_block_till_done()
        # A restored-to-real attribute transition keeps last_changed at NOW.
        assert hass.states.get("binary_sensor.curtailed").last_changed == NOW
        observations = coordinator._observations(clear)
        assert coordinator.input_quality["curtailment_i"] == "clear"
        assert coordinator.input_quality["power_i"] == "ignored:predates_curtailment_clear"
        assert all(obs.curtailed for obs in observations if obs.power_w is not None)
        assert coordinator._curtailment_safe(inv)
    with freeze_time(NOW + timedelta(minutes=3)):
        hass.states.async_set("sensor.energy", "10.02", energy_unit)
        hass.states.async_set("sensor.power", "200", power_unit)
        await hass.async_block_till_done()
        assert coordinator.intervals == []  # first real post-recovery anchor
        power = next(obs for obs in coordinator._observations(NOW + timedelta(minutes=3)) if obs.power_w is not None)
        assert not power.curtailed and power.time == NOW + timedelta(minutes=3)
    with freeze_time(NOW + timedelta(minutes=4)):
        hass.states.async_set("sensor.energy", "10.03", energy_unit)
        await hass.async_block_till_done()
        assert len(coordinator.intervals) == 1
        assert coordinator.intervals[0]["start"] == (NOW + timedelta(minutes=3)).isoformat()
        assert coordinator.intervals[0]["energy_kwh"] == pytest.approx(0.01)
    await coordinator.async_close()
