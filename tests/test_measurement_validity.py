"""Source validity gates original reports separately from curtailment."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from freezegun import freeze_time
from homeassistant.core import State
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
import pytest

from custom_components.adaptive_solar.coordinator import AdaptiveSolarCoordinator
from custom_components.adaptive_solar.core.models import InverterConfig, SiteConfig, StringConfig, WeatherForecast, WeatherPoint
from custom_components.adaptive_solar.sensor import AdaptiveSolarSensor
from tests.test_config_flow import INV, SITE, STRING

NOW = datetime(2026, 6, 1, 10, tzinfo=UTC)
FLAG = "binary_sensor.measurement_valid"


def config(kind="ac", flag=FLAG, **extra):
    fields = {"power_entity_id": "sensor.power", "energy_entity_id": "sensor.energy", "measurement_valid_entity_id": flag, **extra}
    stage = InverterConfig("i", 5, **fields) if kind == "ac" else InverterConfig("i", output_type="dc", max_output_kw=5, **fields)
    return SiteConfig(52, 13, "Europe/Berlin", (StringConfig("s", "i", 5, 30, 180),), (stage,))


def coordinator(hass, site=None):
    site = site or config()
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": site.to_dict()})
    entry.add_to_hass(hass)
    return AdaptiveSolarCoordinator(hass, entry, site, AsyncMock()), entry


def powers(c, now):
    return [o for o in c._observations(now) if o.power_w is not None]


@pytest.mark.parametrize("kind", ["ac", "dc"])
def test_optional_serialization_roundtrip_and_positional_compatibility(kind):
    old = config(kind, None).to_dict()
    assert "measurement_valid_entity_id" not in old["inverters"][0]
    bound = config(kind).to_dict()
    assert bound["inverters"][0].pop("measurement_valid_entity_id") == FLAG
    assert bound == old
    assert SiteConfig.from_dict(old).to_dict() == old
    assert SiteConfig.from_dict(config(kind).to_dict()).inverters[0].measurement_valid_entity_id == FLAG
    positional = InverterConfig("i", 5, .95, "sensor.p", "sensor.e", "binary_sensor.c", "ac", None, 0)
    assert positional.efficiency == .95 and positional.measurement_valid_entity_id is None


@pytest.mark.parametrize("bad", ["sensor.valid", "input_boolean.valid", "", "binary_sensor.valid "])
def test_flag_requires_binary_sensor(bad):
    with pytest.raises(ValueError):
        config(flag=bad)


def test_validity_and_curtailment_need_distinct_signals_but_stages_can_share_validity():
    with pytest.raises(ValueError, match="distinct"):
        config(curtailed_entity_id=FLAG)
    original = config()
    shared = replace(original, strings=(*original.strings, StringConfig("s2", "i2", 5, 30, 180)),
                     inverters=(*original.inverters, InverterConfig("i2", 5, measurement_valid_entity_id=FLAG)))
    assert len(shared.inverters) == 2


@pytest.mark.parametrize("kind", ["ac", "dc"])
@pytest.mark.parametrize("bound", [False, True])
async def test_source_flag_changes_history_and_restore_never_restores_anchor(hass, kind, bound):
    with freeze_time(NOW):
        old_flag = FLAG if bound else None
        c, entry = coordinator(hass, config(kind, old_flag))
        await c.async_restore()
        row = {"inverter_id": "i", "start": (NOW - timedelta(minutes=5)).isoformat(), "end": NOW.isoformat(), "observed_at": NOW.isoformat(), "energy_kwh": .1}
        c.intervals = [row]
        await c._store.async_save(c._stored())
        same = AdaptiveSolarCoordinator(hass, entry, config(kind, old_flag), AsyncMock())
        await same.async_restore()
        assert same.intervals == [row] and same.tracker.anchors == {}
        changed = AdaptiveSolarCoordinator(hass, entry, config(kind, None if bound else FLAG), AsyncMock())
        assert changed._history_fingerprint != c._history_fingerprint
        await changed.async_restore()
        assert changed.intervals == [] and changed.tracker.anchors == {}
        another = AdaptiveSolarCoordinator(hass, entry, config(kind, "binary_sensor.other_valid"), AsyncMock())
        assert another._history_fingerprint != changed._history_fingerprint
        for obj in (c, same, changed, another):
            await obj.async_close()


@pytest.mark.parametrize("kind", ["ac", "dc"])
@pytest.mark.parametrize("energy_between", [False, True])
async def test_invalid_burst_latches_then_original_unchanged_reports_reanchor(hass, kind, energy_between):
    with freeze_time(NOW):
        hass.states.async_set(FLAG, "on")
        hass.states.async_set("sensor.power", "1000", {"unit_of_measurement": "W"})
        c, _ = coordinator(hass, config(kind))
        c.async_start_tracking()
        assert not powers(c, NOW)
    with freeze_time(NOW + timedelta(seconds=1)):
        hass.states.async_set("sensor.energy", "10", {"unit_of_measurement": "kWh"})
        hass.states.async_set("sensor.power", "1000", {"unit_of_measurement": "W"})
        await hass.async_block_till_done()
        assert powers(c, NOW + timedelta(seconds=1))[0].power_w == 1000
    with freeze_time(NOW + timedelta(minutes=1)):
        hass.states.async_set("sensor.energy", "10", {"unit_of_measurement": "kWh"})
        await hass.async_block_till_done()
        assert len(c.intervals) == 1 and c.intervals[0]["energy_kwh"] == 0
    with freeze_time(NOW + timedelta(seconds=90)):
        hass.states.async_set(FLAG, "off")
        if energy_between:
            hass.states.async_set("sensor.energy", "10", {"unit_of_measurement": "kWh"})
        hass.states.async_set(FLAG, "on")
        await hass.async_block_till_done()
        assert "i" in c.tracker.dirty and "i" not in c.tracker.anchors
        assert not powers(c, NOW + timedelta(seconds=90))
        assert c.input_quality["curtailment_i"] == "not_configured"
        assert c.input_quality["power_i"] == "ignored:predates_measurement_valid"
    with freeze_time(NOW + timedelta(minutes=2)):
        hass.states.async_set("sensor.energy", "10", {"unit_of_measurement": "kWh"})
        await hass.async_block_till_done()
        assert len(c.intervals) == 1
        assert c.tracker.anchors["i"][0] == NOW + timedelta(minutes=2)
    with freeze_time(NOW + timedelta(minutes=3)):
        hass.states.async_set("sensor.energy", "10.05", {"unit_of_measurement": "kWh"})
        hass.states.async_set("sensor.power", "1000", {"unit_of_measurement": "W"})
        await hass.async_block_till_done()
        assert len(c.intervals) == 2
        assert c.intervals[-1]["start"] == (NOW + timedelta(minutes=2)).isoformat()
        assert c.intervals[-1]["energy_kwh"] == pytest.approx(.05)
        assert powers(c, NOW + timedelta(minutes=3))
    await c.async_close()


@pytest.mark.parametrize("state", ["off", "unknown", "unavailable", None, "restored"])
async def test_invalid_measurements_preserve_environment_and_do_not_claim_curtailment(hass, state):
    with freeze_time(NOW):
        c, _ = coordinator(hass, replace(config(), temperature_entity_id="sensor.temperature"))
        hass.states.async_set(FLAG, "on")
        c.async_start_tracking()
    with freeze_time(NOW + timedelta(seconds=1)):
        if state is None:
            hass.states.async_remove(FLAG)
        else:
            hass.states.async_set(FLAG, "on" if state == "restored" else state, {"restored": True} if state == "restored" else {})
        hass.states.async_set("sensor.energy", "10", {"unit_of_measurement": "kWh"})
        hass.states.async_set("sensor.power", "1000", {"unit_of_measurement": "W"})
        hass.states.async_set("sensor.temperature", "20", {"unit_of_measurement": "°C"})
        await hass.async_block_till_done()
        observations = c._observations(NOW + timedelta(seconds=1))
        assert any(o.temperature_c == 20 for o in observations)
        assert not any(o.power_w is not None or o.curtailed for o in observations)
        assert not c.tracker.anchors and not c.intervals
        assert c.input_quality["measurement_valid_i"] in ("invalid", "unknown")
    await c.async_close()


async def test_cached_and_equal_boundary_energy_cannot_consume_invalidation(hass):
    with freeze_time(NOW):
        hass.states.async_set(FLAG, "on")
        c, _ = coordinator(hass)
        c.async_start_tracking()
        stage = c.site.inverters[0]
        old = State("sensor.energy", "10", {"unit_of_measurement": "kWh"}, last_updated=NOW, last_reported=NOW)
        c._record_energy(stage, old, NOW)
        assert not c.tracker.anchors and "i" in c.tracker.dirty
    with freeze_time(NOW + timedelta(minutes=1)):
        hass.states.async_set("sensor.energy", "10", {"unit_of_measurement": "kWh"})
        await hass.async_block_till_done()
        hass.states.async_set(FLAG, "off")
        hass.states.async_set(FLAG, "on")
        await hass.async_block_till_done()
        c._record_energy(stage, old, NOW + timedelta(minutes=1), reported_at=NOW)
        assert not c.tracker.anchors and "i" in c.tracker.dirty
    await c.async_close()


async def test_first_refresh_before_tracking_preserves_physics_not_cached_power(hass):
    with freeze_time(NOW):
        hass.states.async_set(FLAG, "on")
        hass.states.async_set("sensor.power", "100", {"unit_of_measurement": "W"})
        c, entry = coordinator(hass)
        c.client.async_forecasts.return_value = (WeatherForecast("best_match", NOW, tuple(
            WeatherPoint(NOW + timedelta(hours=h), NOW + timedelta(hours=h + 1), 500, 600, 100, 20, 2, 30)
            for h in range(24))),)
        result = await c._async_update_data()
        c.async_set_updated_data(result)
        assert result.points and not powers(c, NOW)
        assert c.input_quality["power_i"] == "ignored:measurement_invalid_or_not_monitored"
        assert "power_nowcast:i" not in result.model_status
        assert all(p.power_w == p.baseline_w for p in result.points)
        meter = c.learner_status["i"]["training_quality"]["meter"]
        assert meter["energy_source"] == "blocked_measurement_invalid_or_not_monitored"
        assert meter["measurement_validity"] == "valid"
        hass.states.async_set(FLAG, "off")
        c._observations(NOW)
        quality = AdaptiveSolarSensor(c, entry, "i", "quality")
        assert quality.native_value == "degraded"
        assert quality.extra_state_attributes["operational_curtailment"] == "not_configured"
        assert quality.extra_state_attributes["inputs"]["measurement_valid_i"] == "invalid"
    await c.async_close()


@pytest.mark.parametrize("kind", ["ac", "dc"])
async def test_native_flow_and_options_preserve_then_clear_validity_binding(hass, enable_custom_integrations, kind):
    result = await hass.config_entries.flow.async_init("adaptive_solar", context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], SITE)
    stage = {**INV, "measurement_valid_entity_id": FLAG}
    if kind == "dc":
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {**INV, "output_type": "dc"})
        stage = {"id": "roof", "output_type": "dc", "max_output_kw": 5, "measurement_valid_entity_id": FLAG}
    selector = next(v for k, v in result["data_schema"].schema.items() if k.schema == "measurement_valid_entity_id")
    assert selector.config["filter"] == [{"domain": ["binary_sensor"]}]
    result = await hass.config_entries.flow.async_configure(result["flow_id"], stage)
    with patch("custom_components.adaptive_solar.async_setup_entry", new=AsyncMock(return_value=True)):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], STRING)
        await hass.async_block_till_done()
    assert result["type"] == FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert entry.data["site"]["inverters"][0]["measurement_valid_entity_id"] == FLAG
    assert entry.version == 1
    options = await hass.config_entries.options.async_init(entry.entry_id)
    options = await hass.config_entries.options.async_configure(options["flow_id"], SITE)
    field = next(k for k in options["data_schema"].schema if k.schema == "measurement_valid_entity_id")
    assert field.description["suggested_value"] == FLAG
    stage.pop("measurement_valid_entity_id")
    options = await hass.config_entries.options.async_configure(options["flow_id"], stage)
    options = await hass.config_entries.options.async_configure(options["flow_id"], STRING)
    assert options["type"] == FlowResultType.CREATE_ENTRY
    assert "measurement_valid_entity_id" not in entry.options["site"]["inverters"][0]


@pytest.mark.parametrize("force", [False, True])
async def test_repeated_valid_flag_does_not_restart_phase_or_discard_energy_anchor(hass, force):
    with freeze_time(NOW):
        hass.states.async_set(FLAG, "on")
        c, _ = coordinator(hass)
        c.async_start_tracking()
    with freeze_time(NOW + timedelta(seconds=1)):
        hass.states.async_set("sensor.energy", "10", {"unit_of_measurement": "kWh"})
        await hass.async_block_till_done()
    with freeze_time(NOW + timedelta(minutes=1)):
        hass.states.async_set(FLAG, "on", force_update=force)
        await hass.async_block_till_done()
        assert c._measurement_since(c.site.inverters[0]) == NOW
        assert "i" not in c.tracker.dirty
    with freeze_time(NOW + timedelta(minutes=2)):
        hass.states.async_set("sensor.energy", "10", {"unit_of_measurement": "kWh"})
        await hass.async_block_till_done()
        assert len(c.intervals) == 1
        assert c.intervals[0]["start"] == (NOW + timedelta(seconds=1)).isoformat()
        assert c.intervals[0]["energy_kwh"] == 0
    await c.async_close()
