"""Real HA rollback removes platforms, owners and meter listeners before retry."""
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

from freezegun import freeze_time
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import event as ha_event
from homeassistant.helpers.entity_platform import async_get_platforms
from pytest_homeassistant_custom_component.common import MockConfigEntry
import pytest

from custom_components.adaptive_solar import services
from custom_components.adaptive_solar.const import DOMAIN
from custom_components.adaptive_solar.coordinator import AdaptiveSolarCoordinator
from custom_components.adaptive_solar.core.models import InverterConfig, SiteConfig, StringConfig, WeatherForecast, WeatherPoint

NOW = datetime(2026, 6, 1, 10, tzinfo=UTC)


def meter_listener_counts(hass):
    counts = []
    for key in (ha_event._TRACK_STATE_CHANGE_DATA, ha_event._TRACK_STATE_REPORT_DATA):
        data = hass.data.get(key)
        counts.append(len(data.callbacks.get("sensor.rollback_energy", [])) if data else 0)
    return counts


def service_state(hass):
    return [hass.services.has_service(DOMAIN, name) for name in
            (services.SERVICE, services.RESTORE_SERVICE, services.EXPORT_SERVICE)]


@pytest.mark.parametrize("failure", ["refresh", "forward", "registration", "listener", "commit", "registration_close"])
async def test_failed_native_setup_rolls_back_before_successful_reload(hass, enable_custom_integrations, failure, caplog):
    config = SiteConfig(52, 13, "UTC", (StringConfig("s", "i", 5, 30, 180),),
                        (InverterConfig("i", 5, energy_entity_id="sensor.rollback_energy"),))
    entry = MockConfigEntry(domain=DOMAIN, data={"site": config.to_dict()}, options={"archive_export": True})
    entry.add_to_hass(hass)
    weather = WeatherForecast("best_match", NOW,
                              (WeatherPoint(NOW, NOW + timedelta(hours=1), 600, 400, 200, 20, 2, 30),))
    first = True
    coordinators = []
    original_start = AdaptiveSolarCoordinator.async_start_tracking
    original_refresh = AdaptiveSolarCoordinator.async_config_entry_first_refresh
    original_commit = AdaptiveSolarCoordinator.async_commit_setup
    original_forward = hass.config_entries.async_forward_entry_setups
    original_register = services.async_register_reference_service
    original_on_unload = type(entry).async_on_unload

    def start(coordinator):
        original_start(coordinator)
        if first and failure == "registration_close":
            coordinator.export.close = AsyncMock(side_effect=RuntimeError("secondary close failure"))

    async def refresh(coordinator):
        coordinators.append(coordinator)
        await original_refresh(coordinator)
        if first and failure == "refresh":
            raise RuntimeError("primary setup failure")

    async def forward(*args):
        await original_forward(*args)
        if first and failure == "forward":
            raise RuntimeError("primary setup failure")

    def register(*args):
        original_register(*args)
        if first and failure in {"registration", "registration_close"}:
            raise RuntimeError("primary setup failure")

    def on_unload(instance, callback):
        original_on_unload(instance, callback)
        if first and failure == "listener" and callback.__name__ == "remove_listener":
            raise RuntimeError("primary setup failure")

    def commit(coordinator, **kwargs):
        original_commit(coordinator, **kwargs)
        if first and failure == "commit":
            raise RuntimeError("primary setup failure")

    with freeze_time(NOW, real_asyncio=True), patch(
        "custom_components.adaptive_solar.weather.OpenMeteoClient.async_forecasts", new=AsyncMock(return_value=(weather,))), patch.object(
        AdaptiveSolarCoordinator, "async_start_tracking", start), patch.object(
        AdaptiveSolarCoordinator, "async_config_entry_first_refresh", refresh), patch.object(
        AdaptiveSolarCoordinator, "async_commit_setup", commit), patch.object(
        hass.config_entries, "async_forward_entry_setups", forward), patch.object(
        services, "async_register_reference_service", register), patch.object(type(entry), "async_on_unload", on_unload):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.SETUP_ERROR
        errors = [record for record in caplog.records if record.name == "homeassistant.config_entries"
                  and record.getMessage().startswith("Error setting up entry")]
        assert errors[-1].exc_info[1].args == ("primary setup failure",)
        assert not async_get_platforms(hass, DOMAIN)
        # HA preserves registry-backed unavailable placeholders after native
        # unloading; those are not live entities attached to the coordinator.
        assert all(state.state == "unavailable" and state.attributes.get("restored")
                   for state in hass.states.async_all("sensor"))
        assert meter_listener_counts(hass) == [0, 0]
        assert not any(service_state(hass))
        assert not entry.update_listeners and not hass.data.get(services._OWNERS)
        failed = coordinators[0]
        assert not failed._listeners
        assert failed._closing and not failed._persistence_active and not failed._comparison_persistence_active
        assert failed._setup_commit_handle is None
        assert not Path(failed._store.path).exists()
        assert not Path(failed._comparison_store.path).exists()
        assert not failed.export._active

        first = False
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert len(coordinators) == 2 and entry.runtime_data is coordinators[1]
        assert meter_listener_counts(hass) == [1, 1]
        assert len(entry.update_listeners) == 1 and all(service_state(hass))
        assert len(async_get_platforms(hass, DOMAIN)[0].entities) == 10
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert not async_get_platforms(hass, DOMAIN)
        assert meter_listener_counts(hass) == [0, 0]
        assert not any(service_state(hass))


async def test_coordinator_close_finishes_cleanup_and_persistence_after_export_failure(hass):
    config = SiteConfig(52, 13, "UTC", (StringConfig("s", "i", 5, 30, 180),),
                        (InverterConfig("i", 5, energy_entity_id="sensor.rollback_energy"),))
    entry = MockConfigEntry(domain=DOMAIN, data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    coordinator = AdaptiveSolarCoordinator(hass, entry, config, AsyncMock())
    await coordinator.async_restore()
    coordinator.async_start_tracking()
    coordinator.async_commit_setup()
    coordinator.export.close = AsyncMock(side_effect=RuntimeError("export close failed"))
    with pytest.raises(RuntimeError, match="export close failed"):
        await coordinator.async_close()
    assert meter_listener_counts(hass) == [0, 0]
    assert coordinator._closing and not coordinator._persistence_active and not coordinator._comparison_persistence_active
    assert Path(coordinator._store.path).is_file()


async def test_native_unload_releases_services_even_when_coordinator_close_fails(hass, enable_custom_integrations):
    config = SiteConfig(52, 13, "UTC", (StringConfig("s", "i", 5, 30, 180),), (InverterConfig("i", 5),))
    entry = MockConfigEntry(domain=DOMAIN, data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    weather = WeatherForecast("best_match", NOW, (WeatherPoint(NOW, NOW + timedelta(hours=1), 600, 400, 200, 20, 2, 30),))
    with freeze_time(NOW, real_asyncio=True), patch(
        "custom_components.adaptive_solar.weather.OpenMeteoClient.async_forecasts", new=AsyncMock(return_value=(weather,))):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        coordinator = entry.runtime_data
        coordinator.export.close = AsyncMock(side_effect=RuntimeError("export close failed"))
        assert not await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert not async_get_platforms(hass, DOMAIN)
        assert not any(service_state(hass)) and not hass.data.get(services._OWNERS)
        assert coordinator._closing
