"""Malformed source units and native counter unit transitions fail closed."""
from dataclasses import replace
from datetime import timedelta
from unittest.mock import Mock

from freezegun import freeze_time
from homeassistant.core import State
import pytest

from custom_components.adaptive_solar.coordinator import state_number
from tests.test_meter_quality import NOW, coordinator


@pytest.mark.parametrize("unit", [[], {}, ["kWh"], {"unit": "kWh"}, None, True, 1])
@pytest.mark.parametrize("kind", ["power", "energy", "wind", "irradiance", "temperature"])
def test_non_string_source_unit_is_invalid_for_every_numeric_input(kind, unit):
    with freeze_time(NOW):
        assert state_number(State("sensor.source", "1", {"unit_of_measurement": unit}), NOW, kind) is None


@pytest.mark.parametrize("unit", [[], {}])
@pytest.mark.parametrize("kind", ["power", "wind", "irradiance", "temperature"])
async def test_native_malformed_optional_unit_keeps_forecast_and_raw_quality_available(hass, kind, unit):
    instance = coordinator(hass)
    config = replace(instance.site, **({"inverters": (replace(instance.site.inverters[0],
        power_entity_id="sensor.source"),)} if kind == "power" else {f"{kind}_entity_id": "sensor.source"}))
    instance = type(instance)(hass, instance.config_entry, config, instance.client)
    instance.export.enabled = True
    instance.export.record = Mock()
    instance.client.errors = {}
    with freeze_time(NOW):
        hass.states.async_set("binary_sensor.curtailed", "off")
        hass.states.async_set("sensor.source", "1", {"unit_of_measurement": unit})
        forecast = await instance._async_update_data()
        assert forecast.points
        role = "power_i" if kind == "power" else kind
        assert instance.input_quality[role] != "valid"
        raw = instance._raw_state_snapshot(NOW)["sensor.source"]
        assert raw["quality"][role]["normalized_value"] is None
        await instance.async_close()


@pytest.mark.parametrize("unit", [[], {}])
@pytest.mark.parametrize("numeric_change", [False, True])
async def test_native_malformed_energy_unit_breaks_anchor_and_recovery_never_exports_gap(hass, unit, numeric_change):
    instance = coordinator(hass)
    instance.export.enabled = True
    instance.export.record = recorded = Mock()
    for minute, value, declared in ((0, "1", "kWh"), (5, "1.01" if numeric_change else "1", unit),
                                    (10, "1.02", "kWh")):
        with freeze_time(NOW + timedelta(minutes=minute)):
            if minute == 0:
                hass.states.async_set("binary_sensor.curtailed", "off")
                instance.async_start_tracking()
            hass.states.async_set("sensor.energy", value, {"unit_of_measurement": declared})
            await hass.async_block_till_done()
    assert instance.intervals == []
    assert not [call for call in recorded.call_args_list if call.args[0] == "qualified_interval"]
    with freeze_time(NOW + timedelta(minutes=15)):
        hass.states.async_set("sensor.energy", "1.03", {"unit_of_measurement": "kWh"})
        await hass.async_block_till_done()
    assert instance.intervals[0]["start"] == (NOW + timedelta(minutes=10)).isoformat()
    assert instance.intervals[0]["energy_kwh"] == pytest.approx(0.01)
    assert [call.args[1]["start"] for call in recorded.call_args_list
            if call.args[0] == "qualified_interval"] == [(NOW + timedelta(minutes=10)).isoformat()]
    await instance.async_close()


@pytest.mark.parametrize("old_unit,new_unit,value,next_value", [
    ("Wh", "kWh", "1", "1.01"), ("kWh", "Wh", "1", "1001"),
    ("kWh", "MWh", "0.001", "0.00101"), ("MWh", "kWh", "0.001", "1.001"),
    ("Wh", "kWh", "0", "0.01")])
async def test_native_attribute_only_energy_unit_switch_reanchors_without_artificial_energy(
    hass, old_unit, new_unit, value, next_value,
):
    instance = coordinator(hass)
    instance.export.enabled = True
    instance.export.record = recorded = Mock()
    with freeze_time(NOW):
        hass.states.async_set("binary_sensor.curtailed", "off")
        instance.async_start_tracking()
        hass.states.async_set("sensor.energy", value, {"unit_of_measurement": old_unit})
        await hass.async_block_till_done()
    with freeze_time(NOW + timedelta(minutes=5)):
        old = hass.states.get("sensor.energy")
        hass.states.async_set("sensor.energy", value, {"unit_of_measurement": new_unit})
        new = hass.states.get("sensor.energy")
        assert new.last_changed == old.last_changed and new.last_updated != old.last_updated
        await hass.async_block_till_done()
    with freeze_time(NOW + timedelta(minutes=15)):
        hass.states.async_set("sensor.energy", next_value, {"unit_of_measurement": new_unit})
        await hass.async_block_till_done()
    assert instance.intervals == []
    assert not [call for call in recorded.call_args_list if call.args[0] == "qualified_interval"]
    # A genuine unchanged report after the new anchor can establish zero;
    # the metadata switch itself must never act as a meter endpoint.
    with freeze_time(NOW + timedelta(minutes=20)):
        hass.states.async_set("sensor.energy", next_value, {"unit_of_measurement": new_unit})
        await hass.async_block_till_done()
    assert instance.intervals[0]["start"] == (NOW + timedelta(minutes=15)).isoformat()
    assert instance.intervals[0]["energy_kwh"] == 0
    await instance.async_close()


@pytest.mark.parametrize("forced", [False, True])
async def test_native_same_unit_metadata_and_forced_reports_preserve_continuity(hass, forced):
    instance = coordinator(hass)
    for minute, value, attrs in ((0, "1", {}), (5, "1", {"icon": "mdi:flash"}),
                                 (15, "1.01", {"icon": "mdi:flash"})):
        with freeze_time(NOW + timedelta(minutes=minute)):
            if minute == 0:
                hass.states.async_set("binary_sensor.curtailed", "off")
                instance.async_start_tracking()
            hass.states.async_set("sensor.energy", value, {"unit_of_measurement": "kWh", **attrs},
                                  force_update=forced and minute == 5)
            await hass.async_block_till_done()
    assert instance.intervals[0]["start"] == NOW.isoformat()
    assert sum(row["energy_kwh"] for row in instance.intervals) == pytest.approx(0.01)
    assert len({row["continuity_id"] for row in instance.intervals}) == 1
    assert not instance.tracker.events["i"]["counter_unit_changed"]
    await instance.async_close()


@pytest.mark.parametrize("force_report", [False, True])
async def test_native_unit_change_with_genuine_report_anchors_that_report(hass, force_report):
    instance = coordinator(hass)
    for minute, value, unit in ((0, "1000", "Wh"), (5, "1000" if force_report else "1", "kWh"),
                                (10, "1000.01" if force_report else "1.01", "kWh")):
        with freeze_time(NOW + timedelta(minutes=minute)):
            if minute == 0:
                hass.states.async_set("binary_sensor.curtailed", "off")
                instance.async_start_tracking()
            hass.states.async_set("sensor.energy", value, {"unit_of_measurement": unit},
                                  force_update=force_report and minute == 5)
            await hass.async_block_till_done()
        if minute == 5:
            assert instance.intervals == []
            assert instance.tracker.anchors["i"][0] == NOW + timedelta(minutes=5)
    assert instance.intervals[0]["start"] == (NOW + timedelta(minutes=5)).isoformat()
    assert instance.intervals[0]["energy_kwh"] == pytest.approx(0.01)
    assert instance.intervals[0]["boundary_reason"] == "counter_unit_changed"
    await instance.async_close()


async def test_native_unit_roundtrip_discards_pending_quantized_delta(hass):
    instance = coordinator(hass)
    instance.export.enabled = True
    instance.export.record = recorded = Mock()
    reports = ((0, "1", "kWh"), (0.001, "1.001", "kWh"), (300, "1.001", "Wh"),
               (600, "1.001", "kWh"), (900, "1.002", "kWh"), (1200, "1.003", "kWh"))
    for seconds, value, unit in reports:
        with freeze_time(NOW + timedelta(seconds=seconds)):
            if seconds == 0:
                hass.states.async_set("binary_sensor.curtailed", "off")
                instance.async_start_tracking()
            hass.states.async_set("sensor.energy", value, {"unit_of_measurement": unit})
            await hass.async_block_till_done()
        if seconds == 0.001:
            assert "i" in instance.tracker.pending
        elif seconds >= 300:
            assert "i" not in instance.tracker.pending
        if seconds <= 900:
            assert instance.intervals == []
    assert instance.intervals[0]["start"] == (NOW + timedelta(minutes=15)).isoformat()
    assert instance.intervals[0]["energy_kwh"] == pytest.approx(0.001)
    assert [call.args[1]["start"] for call in recorded.call_args_list
            if call.args[0] == "qualified_interval"] == [(NOW + timedelta(minutes=15)).isoformat()]
    await instance.async_close()


@pytest.mark.parametrize("unit", [[], {}, None, "W"])
async def test_native_attribute_only_unit_recovery_waits_for_genuine_report(hass, unit):
    instance = coordinator(hass)
    for minute, value, declared in ((0, "1", "kWh"), (5, "1", unit), (10, "1", "kWh"),
                                    (15, "1", "kWh"), (20, "1.01", "kWh")):
        with freeze_time(NOW + timedelta(minutes=minute)):
            if minute == 0:
                hass.states.async_set("binary_sensor.curtailed", "off")
                instance.async_start_tracking()
            hass.states.async_set("sensor.energy", value, {"unit_of_measurement": declared})
            await hass.async_block_till_done()
        if minute <= 15:
            assert instance.intervals == []
    assert instance.intervals[0]["start"] == (NOW + timedelta(minutes=15)).isoformat()
    assert instance.intervals[0]["energy_kwh"] == pytest.approx(0.01)
    await instance.async_close()


async def test_native_unit_boundary_preserves_prior_measured_history_and_separates_new_lineage(hass):
    instance = coordinator(hass)
    previous = None
    for minute, value, unit in ((0, "1", "Wh"), (5, "1.1", "Wh"), (10, "1.1", "kWh"),
                                (20, "1.11", "kWh"), (25, "1.12", "kWh")):
        with freeze_time(NOW + timedelta(minutes=minute)):
            if minute == 0:
                hass.states.async_set("binary_sensor.curtailed", "off")
                instance.async_start_tracking()
            hass.states.async_set("sensor.energy", value, {"unit_of_measurement": unit})
            await hass.async_block_till_done()
        if minute == 5:
            previous = instance.intervals[0]
        elif minute in (10, 20):
            assert instance.intervals == [previous]
    assert len(instance.intervals) == 2
    assert instance.intervals[0] == previous
    later = instance.intervals[1]
    assert later["start"] == (NOW + timedelta(minutes=20)).isoformat()
    assert later["energy_kwh"] == pytest.approx(0.01)
    assert later["continuity_id"] != previous["continuity_id"]
    assert later["boundary_reason"] == "counter_unit_changed"
    await instance.async_close()
