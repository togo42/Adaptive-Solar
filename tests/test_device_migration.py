"""Real HA upgrade/reload keeps references while removing duplicate devices."""
from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock, patch

from freezegun import freeze_time
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
import pytest

from custom_components.adaptive_solar.const import DOMAIN
from custom_components.adaptive_solar.core.models import WeatherForecast, WeatherPoint
from custom_components.adaptive_solar.energy import async_get_solar_forecast
from tests.test_dc_ha import NOW, site

KEYS = ("power", "remaining", *(f"day_{day}" for day in range(7)), "quality")


def rows(hass, entry):
    return er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)


def devices(hass, entry):
    return dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)


def weather():
    return WeatherForecast("best_match", NOW, tuple(WeatherPoint(NOW + timedelta(hours=h), NOW + timedelta(hours=h + 1),
                                                                 500, 600, 100, 20, 2, 30) for h in range(48)))


@pytest.mark.parametrize("kind", ["ac", "dc"])
async def test_upgrade_merges_devices_preserves_ids_user_choices_energy_and_history(hass, enable_custom_integrations, kind):
    cfg = site((kind,))
    entry = MockConfigEntry(domain=DOMAIN, data={"site": cfg.to_dict()})
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    total_scope = "dc_site" if kind == "dc" else "site"
    old_device = dr.async_get(hass).async_get_or_create(config_entry_id=entry.entry_id,
                         identifiers={(DOMAIN, f"{entry.entry_id}_{total_scope}")}, name="Legacy total")
    legacy = {}
    for key in KEYS:
        row = registry.async_get_or_create("sensor", DOMAIN, f"{entry.entry_id}_{total_scope}_{key}",
                         config_entry=entry, device_id=old_device.id,
                         suggested_object_id=f"legacy_{key}")
        legacy[key] = row.entity_id
    registry.async_update_entity(legacy["quality"], hidden_by=er.RegistryEntryHider.USER, name="My status")
    registry.async_update_entity(legacy["day_6"], disabled_by=er.RegistryEntryDisabler.USER)
    with freeze_time(NOW, real_asyncio=True), patch("custom_components.adaptive_solar.weather.OpenMeteoClient.async_forecasts",
                                                   new=AsyncMock(return_value=(weather(),))):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert len(devices(hass, entry)) == 1
        assert dr.async_get(hass).async_get(old_device.id) is None
        assert len(rows(hass, entry)) == 20
        before = {row.entity_id: row.unique_id for row in rows(hass, entry)}
        for key, identifier in legacy.items():
            row = registry.async_get(identifier)
            assert row.unique_id == f"{entry.entry_id}_{total_scope}_{key}"
            assert row.hidden_by is (er.RegistryEntryHider.USER if key == "quality" else er.RegistryEntryHider.INTEGRATION)
        assert registry.async_get(legacy["quality"]).name == "My status"
        assert registry.async_get(legacy["day_6"]).disabled_by is er.RegistryEntryDisabler.USER
        stage_power = next(row for row in rows(hass, entry) if "inverter_" in row.unique_id and row.unique_id.endswith("_power"))
        assert hass.states.get(legacy["power"]).state == hass.states.get(stage_power.entity_id).state
        energy = await async_get_solar_forecast(hass, entry.entry_id)
        fingerprint = entry.runtime_data._history_fingerprint
        measured = {"inverter_id": "i0", "start": (NOW - timedelta(hours=1)).isoformat(),
                    "end": (NOW - timedelta(minutes=30)).isoformat(), "observed_at": NOW.isoformat(), "energy_kwh": .5}
        entry.runtime_data.intervals = [measured]
        for _ in range(2):
            assert await hass.config_entries.async_unload(entry.entry_id)
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
            assert {row.entity_id: row.unique_id for row in rows(hass, entry)} == before
            assert len(devices(hass, entry)) == 1
            assert entry.runtime_data._history_fingerprint == fingerprint
            assert entry.runtime_data.intervals == [measured]
            assert await async_get_solar_forecast(hass, entry.entry_id) == energy
        assert await hass.config_entries.async_unload(entry.entry_id)


async def test_one_many_one_cycle_and_multiple_strings_leave_no_orphans(hass, enable_custom_integrations):
    cfg = site(("ac",))
    cfg = replace(cfg, strings=(*cfg.strings, replace(cfg.strings[0], id="second_string", azimuth_deg=90)))
    entry = MockConfigEntry(domain=DOMAIN, data={"site": cfg.to_dict()})
    entry.add_to_hass(hass)
    with freeze_time(NOW, real_asyncio=True), patch("custom_components.adaptive_solar.weather.OpenMeteoClient.async_forecasts",
                                                   new=AsyncMock(return_value=(weather(),))):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert len(rows(hass, entry)) == 10 and len(devices(hass, entry)) == 1
        original = {row.entity_id for row in rows(hass, entry)}
        for configured, count, device_count in ((site(("ac", "ac")), 30, 3), (cfg, 20, 1),
                                                (site(("ac", "ac")), 30, 3), (cfg, 20, 1)):
            assert await hass.config_entries.async_unload(entry.entry_id)
            hass.config_entries.async_update_entry(entry, options={"site": configured.to_dict()})
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
            current = rows(hass, entry)
            assert len(current) == count and len(devices(hass, entry)) == device_count
            assert original <= {row.entity_id for row in current}
            aggregates = [row for row in current if row.unique_id.startswith(f"{entry.entry_id}_site_")]
            expected = None if device_count == 3 else er.RegistryEntryHider.INTEGRATION
            assert all(row.hidden_by is expected for row in aggregates)
        assert await hass.config_entries.async_unload(entry.entry_id)
