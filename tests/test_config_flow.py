"""Exercise real HA config-entry flow handling and selectors."""
from unittest.mock import AsyncMock, patch

import probatio as vol
import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_solar.const import DOMAIN
from custom_components.adaptive_solar.core.models import MAX_FORECAST_DAYS, InverterConfig, SiteConfig, StringConfig

SITE = {"latitude": 52.1, "longitude": 13.1, "timezone": "Europe/Berlin", "weather_models": ["best_match", "icon_d2"], "forecast_days": 7}
INV = {"id": "roof", "max_ac_kw": 5, "efficiency": 0.96, "power_entity_id": "sensor.power", "energy_entity_id": "sensor.energy", "curtailed_entity_id": "input_boolean.curtailed", "add_another": False}
STRING = {"id": "south", "inverter_id": "roof", "peak_kw": 6, "tilt_deg": 30, "azimuth_deg": 180, "loss_fraction": 0.14, "temperature_coefficient": -0.004, "horizon": [{"azimuth_deg": 180, "elevation_deg": 15, "beam_transmission": 0.3}], "add_another": False}


@pytest.mark.parametrize("days", [8, 16])
async def test_native_site_selector_shares_model_seven_day_maximum(hass, enable_custom_integrations, days):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    schema = result["data_schema"]
    selected = next(value for key, value in schema.schema.items() if key.schema == "forecast_days")
    assert selected.config["max"] == MAX_FORECAST_DAYS == 7
    assert schema(SITE)["forecast_days"] == 7
    with pytest.raises(vol.Invalid):
        schema({**SITE, "forecast_days": days})


async def test_complete_native_flow_multiple_inverters_strings_and_sensor_bindings(hass, enable_custom_integrations):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "site"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], SITE)
    assert result["step_id"] == "inverter"
    schema = result["data_schema"].schema
    power_selector = next(value for key, value in schema.items() if key.schema == "power_entity_id")
    assert power_selector.config["filter"][0]["device_class"] == ["power"]
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {**INV, "add_another": True})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {**INV, "id": "shed", "power_entity_id": "sensor.shed_power", "energy_entity_id": "sensor.shed_energy"})
    assert result["step_id"] == "string"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {**STRING, "add_another": True})
    with patch("custom_components.adaptive_solar.async_setup_entry", new=AsyncMock(return_value=True)):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {**STRING, "id": "east", "inverter_id": "shed", "azimuth_deg": 90})
        await hass.async_block_till_done()
    assert result["type"] == FlowResultType.CREATE_ENTRY
    saved = SiteConfig.from_dict(result["data"]["site"])
    assert len(saved.strings) == len(saved.inverters) == 2
    assert saved.inverters[0].energy_entity_id == "sensor.energy"
    assert saved.strings[0].horizon[0].beam_transmission == 0.3


async def test_invalid_timezone_duplicate_id_and_invalid_horizon_are_form_errors(hass, enable_custom_integrations):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {**SITE, "timezone": "nonsense"})
    assert result["errors"] == {"timezone": "invalid_timezone"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], SITE)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {**INV, "add_another": True})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], INV)
    assert result["errors"] == {"base": "invalid_inverter"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {**INV, "id": "second", "remove": True})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {**STRING, "horizon": [{"azimuth_deg": 180, "elevation_deg": 15}, {"azimuth_deg": 180, "elevation_deg": 25}]})
    assert result["errors"] == {"base": "invalid_string"}


async def test_options_edit_existing_equipment_and_preserve_stable_id(hass, enable_custom_integrations):
    site = SiteConfig(52, 13, "Europe/Berlin", (StringConfig("south", "roof", 5, 30, 180),), (InverterConfig("roof", 5),))
    entry = MockConfigEntry(domain=DOMAIN, data={"site": site.to_dict()})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "site"
    result = await hass.config_entries.options.async_configure(result["flow_id"], SITE)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {**INV, "max_ac_kw": 4})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {**STRING, "peak_kw": 7})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options["site"]["inverters"][0]["max_ac_kw"] == 4
    assert entry.options["site"]["strings"][0]["id"] == "south"
