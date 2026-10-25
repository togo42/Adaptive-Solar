"""Unit/coverage semantics and real HA setup/unload without network."""
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

from freezegun import freeze_time
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_solar.const import DOMAIN
from custom_components.adaptive_solar.coordinator import AdaptiveSolarCoordinator
from custom_components.adaptive_solar.core.models import ForecastPoint, ForecastResult, InverterConfig, SiteConfig, StringConfig, WeatherForecast, WeatherPoint
from custom_components.adaptive_solar.energy import async_get_solar_forecast
from custom_components.adaptive_solar.sensor import AdaptiveSolarSensor, day_bounds

NOW = datetime(2026, 6, 1, 10, tzinfo=UTC)


def site(two=False):
    return SiteConfig(52, 13, "Europe/Berlin", tuple(StringConfig(f"s{i}", f"i{i}", 5, 30, 180) for i in range(2 if two else 1)), tuple(InverterConfig(f"i{i}", 5) for i in range(2 if two else 1)))


def test_real_local_midnight_handles_both_dst_transitions():
    for now, hours in [(datetime(2026, 3, 29, 12, tzinfo=UTC), 23), (datetime(2026, 10, 25, 12, tzinfo=UTC), 25)]:
        start, end = day_bounds(now, "Europe/Berlin", 0)
        assert (end - start).total_seconds() == hours * 3600


async def test_site_total_never_sums_partial_inverter_coverage(hass):
    config = site(two=True)
    entry = MockConfigEntry(domain=DOMAIN, data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    point = ForecastPoint(NOW, NOW + timedelta(hours=1), "i0", 1000, 1000)
    coordinator = Mock(site=config, data=ForecastResult(NOW, (point,)), last_update_success=True)
    entry.runtime_data = coordinator
    total = AdaptiveSolarSensor(coordinator, entry, None, "power")
    own = AdaptiveSolarSensor(coordinator, entry, "i0", "power")
    with freeze_time(NOW + timedelta(minutes=5)):
        assert own.native_value == 1000
        assert total.native_value is None
        assert total.available is False
    assert await async_get_solar_forecast(hass, entry.entry_id) is None
    coordinator.data = ForecastResult(NOW, (point, ForecastPoint(NOW, NOW + timedelta(hours=1), "i1", 2000, 2000)))
    assert (await async_get_solar_forecast(hass, entry.entry_id))["wh_hours"][NOW.isoformat()] == 3000


async def test_real_ha_entry_setup_entities_energy_provider_and_unload(hass, enable_custom_integrations):
    assert AdaptiveSolarCoordinator is not None
    config = site()
    entry = MockConfigEntry(domain=DOMAIN, data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    weather = WeatherForecast("best_match", NOW, tuple(WeatherPoint(NOW + timedelta(hours=h), NOW + timedelta(hours=h + 1), 500, 600, 100, 20, 2, 30) for h in range(48)))
    with freeze_time(NOW), patch("custom_components.adaptive_solar.weather.OpenMeteoClient.async_forecasts", new=AsyncMock(return_value=(weather,))):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.runtime_data.data.points
        entities = [state for state in hass.states.async_all("sensor") if state.entity_id.startswith("sensor.adaptive_solar")]
        assert len(entities) == 20
        powers = [state for state in entities if state.attributes.get("device_class") == "power"]
        assert len(powers) == 2
        assert all(state.attributes["unit_of_measurement"] == "W" and state.state != "unavailable" for state in powers)
        energies = [state for state in entities if state.attributes.get("device_class") == "energy"]
        assert all("state_class" not in state.attributes for state in energies)
        qualities = [state for state in entities if state.attributes.get("device_class") == "enum"]
        assert len(qualities) == 2
        assert all(state.state == "physics" for state in qualities)
        assert all(set(state.attributes["options"]) == {"complete", "mixed", "partial", "degraded", "physics", "curtailed"}
                   for state in qualities)
        assert all(state.attributes["forecast_scope"] == "available_pv_potential_without_operational_curtailment"
                   for state in powers + energies + qualities)
        provider = await async_get_solar_forecast(hass, entry.entry_id)
        assert provider and provider["wh_hours"]
        coordinator = entry.runtime_data
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert coordinator._unsub is None


async def test_day_zero_uses_only_archived_snapshot_as_of_local_midnight(hass):
    config = site()
    entry = MockConfigEntry(domain=DOMAIN, data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    midnight, end = day_bounds(NOW, config.timezone, 0)
    result = ForecastResult(NOW, (ForecastPoint(NOW, NOW + timedelta(hours=1), "i0", 9000, 9000),))
    coordinator = Mock(site=config, data=result, daily_snapshots={}, last_update_success=True)
    sensor = AdaptiveSolarSensor(coordinator, entry, None, "day", 0)
    with freeze_time(NOW):
        assert sensor.native_value is None
        coordinator.daily_snapshots = {"2026-06-01": {"issued_at": (midnight - timedelta(hours=1)).isoformat(), "energies": {"i0": 24}}}
        assert sensor.native_value == 24
        # Today's later/current revisions cannot alter this day-start estimate.
        coordinator.data = ForecastResult(NOW + timedelta(minutes=5), (ForecastPoint(NOW, NOW + timedelta(hours=1), "i0", 9500, 9500),))
        assert sensor.native_value == 24
        assert sensor.extra_state_attributes["forecast_cutoff"] == midnight.isoformat()


async def test_inverter_named_total_has_distinct_site_unique_ids(hass):
    config = SiteConfig(52, 13, "UTC", (StringConfig("s", "total", 5, 30, 180),), (InverterConfig("total", 5),))
    entry = MockConfigEntry(domain=DOMAIN, data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    coordinator = Mock(site=config, data=None)
    total = AdaptiveSolarSensor(coordinator, entry, None, "power")
    inverter = AdaptiveSolarSensor(coordinator, entry, "total", "power")
    assert total.unique_id != inverter.unique_id
    assert total.device_info["identifiers"] != inverter.device_info["identifiers"]


async def test_setup_platform_failure_removes_listener_and_shuts_down(hass):
    from custom_components.adaptive_solar import async_setup_entry

    config = SiteConfig(52, 13, "UTC", (StringConfig("s", "i", 5, 30, 180),), (InverterConfig("i", 5, energy_entity_id="sensor.energy"),))
    entry = MockConfigEntry(domain=DOMAIN, data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    with patch("custom_components.adaptive_solar.coordinator.AdaptiveSolarCoordinator.async_config_entry_first_refresh", new=AsyncMock()), patch.object(hass.config_entries, "async_forward_entry_setups", new=AsyncMock(side_effect=RuntimeError("platform failed"))):
        with pytest.raises(RuntimeError, match="platform failed"):
            await async_setup_entry(hass, entry)
    assert entry.runtime_data._unsub is None
