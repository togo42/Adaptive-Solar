"""Independent integration review regressions using real HA state semantics."""
import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

from freezegun import freeze_time
from homeassistant.core import State
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_solar.const import DOMAIN
from custom_components.adaptive_solar.coordinator import AdaptiveSolarCoordinator
from custom_components.adaptive_solar.core.models import (
    InverterConfig, SiteConfig, StringConfig, WeatherForecast, WeatherPoint,
)

NOW = datetime(2026, 6, 1, 10, tzinfo=UTC)


def site(**kwargs):
    return SiteConfig(52, 13, "Europe/Berlin", (StringConfig("s", "i", 5, 30, 180),),
                      (InverterConfig("i", 5, power_entity_id="sensor.power", energy_entity_id="sensor.energy"),),
                      **kwargs)


def coordinator(hass, config=None, client=None):
    config = config or site()
    entry = MockConfigEntry(domain=DOMAIN, data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    return AdaptiveSolarCoordinator(hass, entry, config, client or AsyncMock())


async def test_repeated_fresh_reports_retain_measurement_freshness(hass):
    config = site(temperature_entity_id="sensor.temperature", wind_entity_id="sensor.wind")
    coordinator_ = coordinator(hass, config)
    with freeze_time(NOW - timedelta(hours=1)):
        hass.states.async_set("sensor.power", "1000", {"unit_of_measurement": "W"})
        hass.states.async_set("sensor.temperature", "20", {"unit_of_measurement": "°C"})
        hass.states.async_set("sensor.wind", "2", {"unit_of_measurement": "m/s"})
    with freeze_time(NOW):
        # HA advances last_reported on an unchanged state while preserving
        # last_updated; these are fresh device reports, not stale measurements.
        hass.states.async_set("sensor.power", "1000", {"unit_of_measurement": "W"})
        hass.states.async_set("sensor.temperature", "20", {"unit_of_measurement": "°C"})
        hass.states.async_set("sensor.wind", "2", {"unit_of_measurement": "m/s"})
        observations = coordinator_._observations(NOW)
    assert coordinator_.input_quality["power_i"] == "valid"
    assert len(observations) == 3
    assert all(observation.time == NOW for observation in observations)
    await coordinator_.async_close()


async def test_high_frequency_meter_preserves_energy_without_exhausting_history(hass):
    coordinator_ = coordinator(hass)
    inverter = coordinator_.site.inverters[0]
    for index in range(241):
        stamp = NOW + timedelta(seconds=5 * index)
        energy = 20 + 500 * (5 * index) / 3600000
        state = State("sensor.energy", str(energy), {"unit_of_measurement": "kWh"},
                      last_updated=stamp, last_reported=stamp)
        coordinator_._record_energy(inverter, state, stamp)
    # Two real contiguous intervals can hold these 240 meter deltas. Their
    # labels remain measured means, without splitting energy across boundaries.
    assert len(coordinator_.intervals) <= 2
    assert sum(row["energy_kwh"] for row in coordinator_.intervals) == pytest.approx(500 / 3 / 1000)
    for row in coordinator_.intervals:
        duration = (datetime.fromisoformat(row["end"]) - datetime.fromisoformat(row["start"])).total_seconds()
        assert 0 < duration <= 3600
        assert row["energy_kwh"] * 3600000 / duration == pytest.approx(500)
    await coordinator_.async_close()


async def test_options_can_remove_existing_optional_site_sensor_bindings(hass, enable_custom_integrations):
    config = site(temperature_entity_id="sensor.temperature", wind_entity_id="sensor.wind")
    entry = MockConfigEntry(domain=DOMAIN, data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    site_input = {key: value for key, value in config.to_dict().items()
                  if key not in ("inverters", "strings", "temperature_entity_id", "wind_entity_id") and value is not None}
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], site_input)
    inverter_input = {key: value for key, value in config.to_dict()["inverters"][0].items() if value is not None}
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {**inverter_input, "add_another": False})
    flow = await hass.config_entries.options.async_configure(flow["flow_id"],
                                                           {**config.to_dict()["strings"][0], "add_another": False})
    assert flow["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options["site"].get("temperature_entity_id") is None
    assert entry.options["site"].get("wind_entity_id") is None


async def test_close_cannot_schedule_new_persistence_from_inflight_weather_update(hass):
    started, release = asyncio.Event(), asyncio.Event()
    weather = WeatherForecast("best_match", NOW, (
        WeatherPoint(NOW, NOW + timedelta(hours=1), 500, 600, 100, 20, 2, 30),))

    async def waiting_weather(now):
        started.set()
        await release.wait()
        return (weather,)

    client = AsyncMock()
    client.async_forecasts.side_effect = waiting_weather
    coordinator_ = coordinator(hass, client=client)
    coordinator_._store.async_save = AsyncMock()
    coordinator_._store.async_delay_save = Mock()
    with freeze_time(NOW):
        update = asyncio.create_task(coordinator_._async_update_data())
        await started.wait()
        await coordinator_.async_close()
        release.set()
        await asyncio.gather(update, return_exceptions=True)
    # Unloaded coordinators must not mutate archives or enqueue a delayed Store
    # write after async_close saved the final snapshot (reload race).
    assert coordinator_._store.async_delay_save.call_count == 0
    assert coordinator_.archive == []


async def test_measured_interval_extension_cannot_change_executor_snapshot(hass, monkeypatch):
    from custom_components.adaptive_solar.core.learning import ResidualLearner

    started, release = asyncio.Event(), asyncio.Event()
    weather = WeatherForecast("best_match", NOW, (
        WeatherPoint(NOW, NOW + timedelta(hours=1), 500, 600, 100, 20, 2, 30),))
    client = AsyncMock()
    client.async_forecasts.return_value = (weather,)
    coordinator_ = coordinator(hass, client=client)
    coordinator_.archive = [{"issued_at": (NOW - timedelta(hours=1)).isoformat(),
                             "start": NOW.isoformat(), "end": (NOW + timedelta(hours=1)).isoformat(),
                             "inverter_id": "i", "baseline_w": 500, "features": {"baseline_w": 500}}]
    first = {"start": (NOW + timedelta(minutes=1)).isoformat(), "end": (NOW + timedelta(minutes=59)).isoformat(),
             "observed_at": (NOW + timedelta(minutes=59)).isoformat(), "inverter_id": "i", "energy_kwh": 0.58}
    coordinator_._append_interval(first)
    captured = []

    def capture_fit(self, samples, as_of, *, diagnostics=None):
        captured.extend(samples)
        return self

    executor = hass.async_add_executor_job

    async def wait_then_run(function, *args):
        started.set()
        await release.wait()
        return await executor(function, *args)

    monkeypatch.setattr(ResidualLearner, "fit", capture_fit)
    monkeypatch.setattr(hass, "async_add_executor_job", wait_then_run)
    with freeze_time(NOW + timedelta(minutes=65), real_asyncio=True):
        update = asyncio.create_task(coordinator_._async_update_data())
        await started.wait()
        coordinator_._append_interval({**first, "start": first["end"],
                                      "end": (NOW + timedelta(minutes=60)).isoformat(),
                                      "observed_at": (NOW + timedelta(minutes=60)).isoformat(), "energy_kwh": 0.02})
        release.set()
        await update
    assert len(captured) == 1
    assert captured[0].end == NOW + timedelta(minutes=59)
    assert captured[0].actual_w == pytest.approx(600)
    # Restore the executor before HA Store's real shutdown persistence call.
    monkeypatch.setattr(hass, "async_add_executor_job", executor)
    await coordinator_.async_close()
