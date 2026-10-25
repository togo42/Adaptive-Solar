"""Supported Core owns schema dependencies and discovers energy.py itself."""
import asyncio
from datetime import UTC, datetime, timedelta
from importlib.metadata import requires
from inspect import unwrap
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from freezegun import freeze_time
import probatio
from homeassistant import config_entries
from homeassistant.components.energy.websocket_api import async_get_energy_platforms, ws_solar_forecast
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_solar.const import DOMAIN
from custom_components.adaptive_solar.coordinator import AdaptiveSolarCoordinator
from custom_components.adaptive_solar.core.models import InverterConfig, SiteConfig, StringConfig, WeatherForecast, WeatherPoint
from custom_components.adaptive_solar.energy import async_get_solar_forecast


async def test_core_declares_schema_library_and_native_flow_imports(hass, enable_custom_integrations):
    assert "probatio==0.13.0" in requires("homeassistant")
    assert config_entries.probatio is probatio
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["step_id"] == "site"
    assert isinstance(result["data_schema"], probatio.Schema)


async def test_core_discovers_and_dispatches_energy_without_manual_registration(hass, enable_custom_integrations):
    now = datetime(2026, 6, 1, 10, tzinfo=UTC)
    site = SiteConfig(52, 13, "UTC", (StringConfig("s", "i", 5, 30, 180),), (InverterConfig("i", 5),))
    entry = MockConfigEntry(domain=DOMAIN, data={"site": site.to_dict()})
    entry.add_to_hass(hass)
    weather = WeatherForecast("best_match", now, (WeatherPoint(now, now + timedelta(hours=1), 600, 400, 200, 20, 2, 30),))
    with freeze_time(now, real_asyncio=True), patch("custom_components.adaptive_solar.weather.OpenMeteoClient.async_forecasts",
                                 new=AsyncMock(return_value=(weather,))):
        assert await hass.config_entries.async_setup(entry.entry_id)
        assert isinstance(entry.runtime_data, AdaptiveSolarCoordinator)
        await hass.async_block_till_done()
        async with asyncio.timeout(10):
            platforms = await async_get_energy_platforms(hass)
        assert platforms[DOMAIN] is async_get_solar_forecast
        manager = SimpleNamespace(data={"energy_sources": [{"type": "solar", "config_entry_solar_forecast": [entry.entry_id]}]})
        connection = Mock()
        await unwrap(ws_solar_forecast)(hass, connection, {"id": 1}, manager)
        message_id, forecasts = connection.send_result.call_args.args
        assert message_id == 1
        assert forecasts[entry.entry_id]["wh_hours"][now.isoformat()] > 0
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
