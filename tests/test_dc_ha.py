"""Explicit measured DC output stages alongside unchanged legacy AC behavior."""
from datetime import UTC, datetime, timedelta
import hashlib
import json
from unittest.mock import AsyncMock, Mock, patch

from freezegun import freeze_time
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
import pytest

from custom_components.adaptive_solar.const import DOMAIN
from custom_components.adaptive_solar.coordinator import AdaptiveSolarCoordinator
from custom_components.adaptive_solar.core.models import ForecastPoint, ForecastResult, InverterConfig, SiteConfig, StringConfig, WeatherForecast, WeatherPoint
from custom_components.adaptive_solar.diagnostics import async_get_config_entry_diagnostics
from custom_components.adaptive_solar.energy import async_get_solar_forecast
from custom_components.adaptive_solar.sensor import AdaptiveSolarSensor
from tests.test_config_flow import INV, SITE, STRING

NOW = datetime(2026, 6, 1, 10, tzinfo=UTC)


def output(identifier="i", kind="dc", cap=3, **kwargs):
    return InverterConfig(identifier, output_type="dc", max_output_kw=cap, **kwargs) if kind == "dc" else InverterConfig(identifier, cap, **kwargs)


def site(kinds=("dc",), *, bound=False):
    stages = tuple(output(f"i{index}", kind, power_entity_id=f"sensor.power_{index}" if bound else None,
                          energy_entity_id=f"sensor.energy_{index}" if bound else None) for index, kind in enumerate(kinds))
    return SiteConfig(52, 13, "Europe/Berlin", tuple(StringConfig(f"s{index}", stage.id, 5, 30, 180) for index, stage in enumerate(stages)), stages)


def entry_for(hass, config):
    entry = MockConfigEntry(domain=DOMAIN, data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    return entry


async def test_dc_flow_has_own_cap_no_ac_efficiency_and_explicit_meter_boundary(hass, enable_custom_integrations):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], SITE)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {**INV, "output_type": "dc"})
    assert result["step_id"] == "dc_inverter"
    schema = result["data_schema"].schema
    keys = {key.schema for key in schema}
    assert {"max_output_kw", "dc_loss_fraction", "output_type"} <= keys
    assert "max_ac_kw" not in keys and "efficiency" not in keys
    # AC sensor references are not preselected when changing boundaries.
    for key in schema:
        if key.schema in ("power_entity_id", "energy_entity_id"):
            assert not key.description
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {
        "id": "roof", "output_type": "dc", "max_output_kw": 2.8, "dc_loss_fraction": 0.02,
        "power_entity_id": "sensor.controller_power", "energy_entity_id": "sensor.controller_yield"})
    assert result["step_id"] == "string"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {**STRING, "add_another": True})
    with patch("custom_components.adaptive_solar.async_setup_entry", new=AsyncMock(return_value=True)):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {**STRING, "id": "east", "azimuth_deg": 90})
        await hass.async_block_till_done()
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert len(result["data"]["site"]["strings"]) == 2
    assert {row["inverter_id"] for row in result["data"]["site"]["strings"]} == {"roof"}
    stored = result["data"]["site"]["inverters"][0]
    assert stored["output_type"] == "dc" and stored["max_output_kw"] == 2.8
    assert stored["dc_loss_fraction"] == 0.02
    assert "max_ac_kw" not in stored and "efficiency" not in stored
    assert stored["energy_entity_id"] == "sensor.controller_yield"


async def test_dc_options_edit_binding_and_switch_to_ac_without_reusing_dc_meter(hass, enable_custom_integrations):
    config = site(bound=True)
    entry = entry_for(hass, config)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], SITE)
    assert result["step_id"] == "dc_inverter"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"id": "i0", "output_type": "ac", "max_output_kw": 3, "power_entity_id": "sensor.power_0", "energy_entity_id": "sensor.energy_0"})
    assert result["step_id"] == "inverter"
    schema = result["data_schema"].schema
    assert {key.schema for key in schema} >= {"max_ac_kw", "efficiency"}
    for key in schema:
        if key.schema in ("power_entity_id", "energy_entity_id"):
            assert not key.description
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"id": "i0", "max_ac_kw": 4, "efficiency": 0.95})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {**STRING, "id": "s0", "inverter_id": "i0"})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    saved = SiteConfig.from_dict(entry.options["site"])
    assert saved.inverters[0].output_type == "ac"
    assert saved.inverters[0].power_entity_id is saved.inverters[0].energy_entity_id is None


async def test_legacy_ac_json_hash_and_entity_ids_remain_exact(hass):
    config = site(("ac",))
    entry = entry_for(hass, config)
    stage = config.to_dict()["inverters"][0]
    assert set(stage) == {"id", "max_ac_kw", "efficiency", "power_entity_id", "energy_entity_id", "curtailed_entity_id"}
    legacy = config.to_dict()
    legacy.pop("irradiance_entity_id")
    coordinator = AdaptiveSolarCoordinator(hass, entry, config, AsyncMock())
    assert coordinator._fingerprint == hashlib.sha256(json.dumps(legacy, sort_keys=True).encode()).hexdigest()[:16]
    total = AdaptiveSolarSensor(coordinator, entry, None, "power")
    own = AdaptiveSolarSensor(coordinator, entry, "i0", "power")
    assert total.unique_id == f"{entry.entry_id}_site_power"
    assert own.unique_id == f"{entry.entry_id}_inverter_i0_power"
    assert own.capability_attributes["measurement_boundary"] == "ac_inverter_output"
    await coordinator.async_close()


async def test_output_type_change_invalidates_history_and_uses_new_entity_namespace(hass):
    ac, dc = site(("ac",)), site(("dc",))
    entry = entry_for(hass, ac)
    original = AdaptiveSolarCoordinator(hass, entry, ac, AsyncMock())
    changed = AdaptiveSolarCoordinator(hass, entry, dc, AsyncMock())
    assert original._fingerprint != changed._fingerprint
    changed._store.async_load = AsyncMock(return_value={"fingerprint": original._fingerprint, "archive": [{"old": "ac"}], "intervals": [{"old": "ac"}], "daily_snapshots": {}})
    await changed.async_restore()
    assert changed.archive == changed.intervals == []
    assert AdaptiveSolarSensor(changed, entry, "i0", "power").unique_id == f"{entry.entry_id}_dc_inverter_i0_power"
    assert AdaptiveSolarSensor(changed, entry, None, "power").unique_id == f"{entry.entry_id}_dc_site_power"
    await original.async_close()
    await changed.async_close()


@pytest.mark.parametrize("kinds,boundary,eligible", [(("ac",), "ac_inverter_output", True), (("dc",), "dc_charge_controller_output", True), (("ac", "dc"), "mixed_output_generation_sum", False)])
async def test_explicit_total_scope_and_energy_eligibility(kinds, boundary, eligible, hass):
    config = site(kinds)
    entry = entry_for(hass, config)
    points = tuple(ForecastPoint(NOW, NOW + timedelta(hours=1), stage.id, 1000, 1000) for stage in config.inverters)
    coordinator = Mock(site=config, data=ForecastResult(NOW, points), last_update_success=True,
                       learner_status={}, input_quality={}, daily_snapshots={}, intervals=[], archive=[])
    entry.runtime_data = coordinator
    total = AdaptiveSolarSensor(coordinator, entry, None, "power")
    assert total.capability_attributes["measurement_boundary"] == boundary
    assert total.capability_attributes["output_types"] == sorted(set(kinds))
    assert total.capability_attributes["native_energy_eligible"] is eligible
    assert total.capability_attributes["output_stage_boundaries"] == {stage.id: stage.measurement_boundary for stage in config.inverters}
    with freeze_time(NOW + timedelta(minutes=5)):
        assert total.native_value == 1000 * len(kinds)
        assert total.extra_state_attributes["measurement_boundary"] == boundary
    provider = await async_get_solar_forecast(hass, entry.entry_id)
    assert (provider is not None) is eligible
    if eligible:
        assert provider["wh_hours"][NOW.isoformat()] == 1000
    else:
        assert total.unique_id == f"{entry.entry_id}_mixed_site_power"
        own = AdaptiveSolarSensor(coordinator, entry, "i1", "power")
        assert own.capability_attributes["measurement_boundary"] == "dc_charge_controller_output"
        assert own.capability_attributes["native_energy_eligible"] is False


async def test_dc_cap_applies_to_live_meter_and_restored_history(hass):
    config = site(bound=True)
    entry = entry_for(hass, config)
    coordinator = AdaptiveSolarCoordinator(hass, entry, config, AsyncMock())
    stage = config.inverters[0]
    with freeze_time(NOW):
        hass.states.async_set(stage.power_entity_id, "3.4", {"unit_of_measurement": "kW"})
        assert not coordinator._observations(NOW)
        hass.states.async_set(stage.energy_entity_id, "10", {"unit_of_measurement": "kWh"})
        coordinator._record_energy(stage, hass.states.get(stage.energy_entity_id), NOW)
    with freeze_time(NOW + timedelta(minutes=5)):
        hass.states.async_set(stage.energy_entity_id, "10.1", {"unit_of_measurement": "kWh"})
        coordinator._record_energy(stage, hass.states.get(stage.energy_entity_id), NOW + timedelta(minutes=5))
    assert len(coordinator.intervals) == 1
    assert coordinator.intervals[0]["energy_kwh"] == pytest.approx(0.1)
    corrupt = {"fingerprint": coordinator._fingerprint, "archive": [], "intervals": [{**coordinator.intervals[0], "energy_kwh": 0.3}], "daily_snapshots": {}}
    coordinator._store.async_load = AsyncMock(return_value=None)
    coordinator._legacy_store.async_load = AsyncMock(return_value=corrupt)
    await coordinator.async_restore()
    assert coordinator.intervals == []  # Legacy 3.6kW exceeds 3kW DC cap *1.1
    await coordinator.async_close()


async def test_native_dc_entry_setup_and_unavailable_entities_keep_boundary(hass, enable_custom_integrations):
    config = site(("dc",))
    entry = entry_for(hass, config)
    weather = WeatherForecast("best_match", NOW, tuple(WeatherPoint(NOW + timedelta(hours=h), NOW + timedelta(hours=h + 1), 600, 700, 100, 20, 2, 30) for h in range(48)))
    with freeze_time(NOW), patch("custom_components.adaptive_solar.weather.OpenMeteoClient.async_forecasts", new=AsyncMock(return_value=(weather,))):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        entities = [state for state in hass.states.async_all("sensor") if state.entity_id.startswith("sensor.adaptive_solar_dc")]
        assert len(entities) == 20
        assert all(state.attributes["measurement_boundary"] == "dc_charge_controller_output" for state in entities)
        assert all(state.attributes["output_type"] == "dc" and state.attributes["native_energy_eligible"] is True for state in entities)
        assert any(state.state == "unavailable" for state in entities)  # cold day0/long-horizon gaps still labelled
        assert await async_get_solar_forecast(hass, entry.entry_id)
        diagnostics = await async_get_config_entry_diagnostics(hass, entry)
        assert diagnostics["output_stages"] == {"dc": 1}
        assert "power_entity_id" not in json.dumps(diagnostics)
        assert await hass.config_entries.async_unload(entry.entry_id)


async def test_mixed_sum_requires_all_stage_coverage_and_keeps_scope_when_unavailable(hass):
    config = site(("ac", "dc"))
    entry = entry_for(hass, config)
    point = ForecastPoint(NOW, NOW + timedelta(hours=1), "i0", 1000, 1000)
    coordinator = Mock(site=config, data=ForecastResult(NOW, (point,)), last_update_success=True,
                       learner_status={}, input_quality={}, daily_snapshots={}, intervals=[], archive=[])
    coordinator.client.errors = {}
    total = AdaptiveSolarSensor(coordinator, entry, None, "power")
    quality = AdaptiveSolarSensor(coordinator, entry, None, "quality")
    with freeze_time(NOW + timedelta(minutes=5)):
        assert total.native_value is None and total.available is False
        assert total.capability_attributes["measurement_boundary"] == "mixed_output_generation_sum"
        assert total.capability_attributes["output_types"] == ["ac", "dc"]
        assert quality.native_value == "partial"
        assert quality.extra_state_attributes["forecast"] == []
    entry.runtime_data = coordinator
    assert await async_get_solar_forecast(hass, entry.entry_id) is None


async def test_duplicate_meter_binding_is_rejected_in_ui_before_string_assignment(hass, enable_custom_integrations):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], SITE)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {**INV, "add_another": True})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {**INV, "id": "controller", "output_type": "dc"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"id": "controller", "max_output_kw": 3, "power_entity_id": INV["power_entity_id"]})
    assert result["step_id"] == "dc_inverter"
    assert result["errors"] == {"base": "invalid_inverter"}
