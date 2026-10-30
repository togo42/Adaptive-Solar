"""Native passive raw reports and immutable chronological shade decisions."""
import base64
from dataclasses import replace
from datetime import timedelta
import json
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID
import zlib

from freezegun import freeze_time
import pytest

from custom_components.adaptive_solar.coordinator import AdaptiveSolarCoordinator
from custom_components.adaptive_solar.core.replay import hydrate_forecast
from tests.test_archive_export import NOW, make_coordinator


@pytest.fixture(autouse=True)
def private_archive_directory(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)


def configured(hass, enabled=True, *, overlap=False):
    instance, entry = make_coordinator(hass, enabled)
    site = replace(instance.site,
        inverters=(replace(instance.site.inverters[0], power_entity_id="sensor.power",
                           energy_entity_id="sensor.power" if overlap else "sensor.energy"),),
        irradiance_entity_id="sensor.ghi", temperature_entity_id="sensor.temp", wind_entity_id="sensor.wind")
    return AdaptiveSolarCoordinator(hass, entry, site, instance.client)


def decode_state(event, events):
    ref = event["payload"]["replay_state"]
    by_id = {item["event_id"]: item for item in events}
    text = "".join(by_id[key]["payload"]["data_fragment"] for key in ref["event_ids"])
    return json.loads(zlib.decompress(base64.b64decode(text)))


@pytest.mark.parametrize("entity,unit", [("sensor.power", "W"), ("sensor.ghi", "W/m²"),
                                          ("sensor.temp", "°C"), ("sensor.wind", "m/s")])
async def test_raw_sources_keep_invalid_restored_unchanged_and_removal(hass, entity, unit):
    instance = configured(hass)
    with freeze_time(NOW, real_asyncio=True):
        instance.async_start_tracking()
        instance.async_commit_setup()
        with patch.object(instance, "_schedule_save") as save, patch.object(instance, "_record_energy") as energy:
            for offset, value, attrs in [(0, "12", {"unit_of_measurement": unit, "private": "omit"}),
                                         (1, "12", {"unit_of_measurement": unit, "private": "omit"}),
                                         (2, "unavailable", {"unit_of_measurement": unit}),
                                         (3, "nan", {"unit_of_measurement": unit, "restored": True})]:
                with freeze_time(NOW + timedelta(seconds=offset), real_asyncio=True):
                    hass.states.async_set(entity, value, attrs)
                    await hass.async_block_till_done()
            with freeze_time(NOW + timedelta(seconds=4), real_asyncio=True):
                hass.states.async_remove(entity)
                await hass.async_block_till_done()
            save.assert_not_called()
            energy.assert_not_called()
        events = (await instance.export.page())["page"]["events"]
        reports = [event for event in events if event["kind"] == "source_report"]
        assert len(reports) == 5
        payloads = [event["payload"] for event in reports]
        assert [item["state"] for item in payloads] == ["12", "12", "unavailable", "nan", None]
        assert [item["event_type"] for item in payloads] == ["state_changed", "state_reported", "state_changed", "state_changed", "state_changed"]
        assert payloads[1]["last_changed"] == NOW.isoformat()
        assert payloads[1]["last_updated"] == NOW.isoformat()
        assert payloads[1]["last_reported"] == (NOW + timedelta(seconds=1)).isoformat()
        assert payloads[3]["attributes"]["restored"] is True
        assert all("private" not in item["attributes"] for item in payloads)
        assert all(item["event_received_at"] == event["received_at"] for item, event in zip(payloads, reports, strict=True))
        await instance.async_close()


async def test_overlap_uses_one_subscription_and_preserves_meter_callbacks(hass):
    instance = configured(hass, overlap=True)
    with freeze_time(NOW, real_asyncio=True):
        instance.async_start_tracking()
        with patch.object(instance, "_record_energy") as energy:
            hass.states.async_set("sensor.power", "12", {"unit_of_measurement": "kWh"})
            await hass.async_block_till_done()
            with freeze_time(NOW + timedelta(seconds=1), real_asyncio=True):
                hass.states.async_set("sensor.power", "12", {"unit_of_measurement": "kWh"})
                await hass.async_block_till_done()
            assert energy.call_count == 2
        instance.async_commit_setup()
        reports = (await instance.export.page())["page"]["events"]
        assert len(reports) == 2
        await instance.async_close()


async def test_default_off_has_no_raw_subscriptions_snapshot_or_reports(hass):
    instance = configured(hass, False)
    target = "custom_components.adaptive_solar.coordinator."
    with patch(target + "async_track_state_change_event") as changed, patch(target + "async_track_state_report_event") as reported:
        instance.async_start_tracking()
        assert changed.call_args.args[1] == ["sensor.energy"]
        assert reported.call_args.args[1] == ["sensor.energy"]
    with freeze_time(NOW, real_asyncio=True), patch.object(instance, "_raw_state_snapshot", side_effect=AssertionError), patch.object(instance.export, "record", side_effect=AssertionError):
        await instance._async_update_data()
        assert instance._shade_step_sequence == 0
        await instance.async_close()


async def test_capture_before_after_accepted_rejected_and_session_seed(hass):
    instance = configured(hass)
    instance.shading.record("i", 180, 45, NOW - timedelta(days=1), 0.8, as_of=NOW - timedelta(days=1))
    seed = instance.shading.to_dict()
    with freeze_time(NOW, real_asyncio=True), patch("custom_components.adaptive_solar.coordinator.solar_position", return_value=SimpleNamespace(azimuth_deg=180, elevation_deg=45)), patch("custom_components.adaptive_solar.coordinator.clear_sky_ghi", return_value=800), patch("custom_components.adaptive_solar.coordinator.shade_reference_powers", return_value=(100, 1000)):
        hass.states.async_set("sensor.power", "550", {"unit_of_measurement": "W"})
        hass.states.async_set("sensor.ghi", "800", {"unit_of_measurement": "W/m²"})
        hass.states.async_set("sensor.temp", "unknown", {"unit_of_measurement": "°C", "restored": True})
        original = instance.shading
        await instance._async_update_data()
        assert original.to_dict() == seed
        instance.async_commit_setup()
        hass.states.async_set("sensor.ghi", "unavailable", {"unit_of_measurement": "W/m²"})
        await instance._async_update_data()
        events = (await instance.export.page())["page"]["events"]
        issued = [hydrate_forecast(event, events) for event in events if event["kind"] == "forecast_issued"]
        first, second = [event["payload"]["shade_learning"] for event in issued]
        before, after = [decode_state(event, events) for event in issued]
        assert before["shading_before"] == seed
        assert before["shading"] != seed
        assert after["shading_before"] == before["shading"] == after["shading"]
        assert first["decisions"]["i"]["accepted"] is True
        assert first["decisions"]["i"]["factor"] == pytest.approx(0.5)
        assert second["decisions"]["i"]["accepted"] is False
        assert "stale_or_unpaired" in second["decisions"]["i"]["reasons"]
        assert first["inputs"]["i"] == first["decisions"]["i"]["input"]
        assert first["schema"] == 1 and first["policy_version"] == "beam-shade-learning-v2"
        assert str(UUID(first["session_id"])) == first["session_id"]
        assert first["initial_state_source"] == "session_seed"
        assert first["initial_state_scope"] == "unverified_preexisting_history"
        assert first["previous_step_id"] is None and first["step_sequence"] == 1
        assert second["previous_step_id"] == first["step_id"] and second["step_sequence"] == 2
        assert second["session_id"] == first["session_id"]
        raw = first["raw_state_snapshot"]
        assert raw["sensor.temp"]["state"] == "unknown"
        assert raw["sensor.temp"]["attributes"]["restored"] is True
        assert raw["sensor.wind"]["state"] is None
        assert raw["sensor.wind"]["last_reported"] is None
        assert raw["sensor.ghi"]["quality"]["irradiance"]["normalized_value"] == 800
        assert second["raw_state_snapshot"]["sensor.ghi"]["state"] == "unavailable"
        await instance.async_close()


@pytest.mark.parametrize("failure", ["serialize", "overflow"])
async def test_missing_export_attempt_stays_in_step_chain_and_restart_has_new_session(hass, failure):
    instance = configured(hass)
    with freeze_time(NOW, real_asyncio=True):
        await instance._async_update_data()
        instance.async_commit_setup()
        await instance.export.page()
        target = "custom_components.adaptive_solar.coordinator.replay_events" if failure == "serialize" else "custom_components.adaptive_solar.archive_export.MAX_PENDING_EVENTS"
        options = {"side_effect": ValueError("test serialization")} if failure == "serialize" else {"new": 0}
        with patch(target, **options):
            await instance._async_update_data()
        missing_step_id = instance._shade_previous_step_id
        await instance.export.page()
        await instance._async_update_data()
        events = (await instance.export.page())["page"]["events"]
        steps = [hydrate_forecast(event, events)["payload"]["shade_learning"] for event in events if event["kind"] == "forecast_issued"]
        assert [step["step_sequence"] for step in steps] == [1, 3]
        assert steps[-1]["previous_step_id"] == missing_step_id
        assert steps[-1]["previous_step_id"] != steps[0]["step_id"]
        restarted = configured(hass)
        await restarted._async_update_data()
        restarted.async_commit_setup()
        events = (await restarted.export.page())["page"]["events"]
        step = next(hydrate_forecast(event, events)["payload"]["shade_learning"] for event in events if event["kind"] == "forecast_issued")
        assert step["session_id"] != steps[0]["session_id"]
        assert step["step_sequence"] == 1 and step["previous_step_id"] is None
        await restarted.async_close()
        await instance.async_close()


async def test_capture_switch_preserves_forecast_learning_and_quality(hass):
    enabled = configured(hass)
    disabled = configured(hass, False)
    with freeze_time(NOW, real_asyncio=True):
        hass.states.async_set("sensor.power", "550", {"unit_of_measurement": "W"})
        hass.states.async_set("sensor.ghi", "800", {"unit_of_measurement": "W/m²"})
        hass.states.async_set("sensor.temp", "20", {"unit_of_measurement": "°C"})
        hass.states.async_set("sensor.wind", "2", {"unit_of_measurement": "m/s"})
        assert await enabled._async_update_data() == await disabled._async_update_data()
        assert enabled.shading.to_dict() == disabled.shading.to_dict()
        assert enabled.learner_status == disabled.learner_status
        assert enabled.input_quality == disabled.input_quality
        await enabled.async_close()
        await disabled.async_close()


@pytest.mark.parametrize("invalid_kind", ["future", "stale", "unit", "nonfinite", "restored"])
async def test_snapshot_keeps_rejected_power_and_original_timestamp(hass, invalid_kind):
    instance = configured(hass)
    stamp = NOW + timedelta(hours=1) if invalid_kind == "future" else NOW - timedelta(hours=1) if invalid_kind == "stale" else NOW
    attrs = {"unit_of_measurement": "kWh" if invalid_kind == "unit" else "W"}
    if invalid_kind == "restored":
        attrs["restored"] = True
    value = "nan" if invalid_kind == "nonfinite" else "100"
    with freeze_time(stamp, real_asyncio=True):
        hass.states.async_set("sensor.power", value, attrs)
    with freeze_time(NOW, real_asyncio=True):
        await instance._async_update_data()
        instance.async_commit_setup()
        events = (await instance.export.page())["page"]["events"]
        payload = next(hydrate_forecast(event, events)["payload"] for event in events if event["kind"] == "forecast_issued")
        raw = payload["shade_learning"]["raw_state_snapshot"]["sensor.power"]
        assert raw["state"] == value and raw["attributes"] == attrs
        assert raw["last_reported"] == stamp.isoformat()
        assert raw["quality"]["power_i"]["normalized_value"] is None
        assert payload["shade_learning"]["inputs"]["i"]["power_w"] is None
        assert payload["shade_learning"]["inputs"]["i"]["power_time"] is None
        await instance.async_close()


@pytest.mark.parametrize("entity,unit", [("sensor.power", "W"), ("sensor.energy", "kWh"),
                                        ("sensor.ghi", "W/m²"), ("sensor.temp", "°C"), ("sensor.wind", "m/s")])
@pytest.mark.parametrize("kind", ["initial", "attributes", "forced"])
async def test_raw_report_burst_keeps_each_original_event_timestamp(hass, entity, unit, kind):
    instance = configured(hass)
    attrs = {"unit_of_measurement": unit}
    if kind != "initial":
        with freeze_time(NOW - timedelta(minutes=1), real_asyncio=True):
            hass.states.async_set(entity, "12", attrs)
            await hass.async_block_till_done()
    with freeze_time(NOW, real_asyncio=True) as clock:
        instance.async_start_tracking()
        instance.async_commit_setup()
        changed_attrs = {**attrs, "extra_attribute": "changed"} if kind == "attributes" else attrs
        # No event-loop flush between updates: HA mutates new_state.last_reported
        # before the initial state_changed callback gets to inspect that object.
        hass.states.async_set(entity, "12", changed_attrs, force_update=kind == "forced")
        for _ in range(2):
            clock.tick(delta=timedelta(seconds=1))
            hass.states.async_set(entity, "12", changed_attrs)
        assert hass.states.get(entity).last_reported == NOW + timedelta(seconds=2)
        await hass.async_block_till_done()
        events = (await instance.export.page())["page"]["events"]
        reports = [event for event in events if event["kind"] == "source_report" and event["payload"]["entity_id"] == entity]
        assert [event["payload"]["event_type"] for event in reports] == ["state_changed", "state_reported", "state_reported"]
        expected = [(NOW + timedelta(seconds=n)).isoformat() for n in range(3)]
        assert [event["payload"]["last_reported"] for event in reports] == expected
        assert [event["received_at"] for event in reports] == expected
        assert all(event["payload"]["last_updated"] == NOW.isoformat() for event in reports)
        await instance.async_close()


@pytest.mark.parametrize("entity,unit", [("sensor.power", "W"), ("sensor.energy", "kWh"),
                                        ("sensor.ghi", "W/m²"), ("sensor.temp", "°C"), ("sensor.wind", "m/s")])
@pytest.mark.parametrize("kind", ["initial", "attributes", "forced"])
async def test_earlier_native_listener_cannot_advance_original_raw_report(hass, entity, unit, kind):
    from homeassistant.core import callback

    instance = configured(hass)
    attrs = {"unit_of_measurement": unit}
    if kind != "initial":
        with freeze_time(NOW - timedelta(minutes=1), real_asyncio=True):
            hass.states.async_set(entity, "12", attrs)
            await hass.async_block_till_done()
    with freeze_time(NOW, real_asyncio=True) as clock:
        changed_attrs = {**attrs, "extra_attribute": "changed"} if kind == "attributes" else attrs
        armed = True

        @callback
        def reports_before_tracker(event):
            nonlocal armed
            if armed and event.data["entity_id"] == entity:
                armed = False
                for _ in range(2):
                    clock.tick(delta=timedelta(seconds=1))
                    hass.states.async_set(entity, "12", changed_attrs)

        # Real HA callbacks are immediate; an earlier listener may synchronously
        # publish more reports before this integration receives the parent change.
        unsubscribe = hass.bus.async_listen("state_changed", reports_before_tracker)
        instance.async_start_tracking()
        instance.async_commit_setup()
        hass.states.async_set(entity, "12", changed_attrs, force_update=kind == "forced")
        assert hass.states.get(entity).last_reported == NOW + timedelta(seconds=2)
        await hass.async_block_till_done()
        events = (await instance.export.page())["page"]["events"]
        reports = [event for event in events if event["kind"] == "source_report" and event["payload"]["entity_id"] == entity]
        changed, = [event for event in reports if event["payload"]["event_type"] == "state_changed"]
        reported = [event for event in reports if event["payload"]["event_type"] == "state_reported"]
        assert changed["received_at"] == NOW.isoformat()
        assert changed["payload"]["last_reported"] == NOW.isoformat()
        assert [event["payload"]["last_reported"] for event in reported] == [
            (NOW + timedelta(seconds=n)).isoformat() for n in (1, 2)]
        assert all(event["payload"]["last_reported"] <= event["received_at"] for event in reports)
        unsubscribe()
        await instance.async_close()
