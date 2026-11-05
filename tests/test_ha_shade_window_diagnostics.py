"""Native coordinator/sensor visibility adds no model or replay state."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock, patch

from freezegun import freeze_time
import pytest

from custom_components.adaptive_solar.coordinator import AdaptiveSolarCoordinator, join_training
from custom_components.adaptive_solar.core.models import InverterConfig, StringConfig
from custom_components.adaptive_solar.core.replay import hydrate_forecast
from custom_components.adaptive_solar.core.shading import BEAM_SHADE_STORE_KEY, BeamShadeTable
from custom_components.adaptive_solar.sensor import AdaptiveSolarSensor
from tests.storage_helpers import seed_store
from tests.test_archive_export import NOW, make_coordinator
from tests.test_learning_persistence import coordinator, evidence
from tests.test_shade_capture import decode_state


def populate(table, *, stage="i", azimuth=180, elevation=40, factor=0.5):
    for day, minute in ((2, 30), (2, 15), (2, 0), (1, 15), (1, 0)):
        at = NOW - timedelta(days=day, minutes=minute)
        assert table.record(stage, azimuth, elevation, at, factor, as_of=at)


@pytest.fixture(autouse=True)
def isolated_config_directory(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)


async def test_native_setup_sensor_and_reload_expose_all_stored_stage_windows(hass, enable_custom_integrations):
    template, entry = make_coordinator(hass)
    site = replace(template.site,
        strings=(*template.site.strings, StringConfig("second", "j", 3, 20, 270)),
        inverters=(*template.site.inverters, InverterConfig("j", 3)))
    hass.config_entries.async_update_entry(entry, data={"site": site.to_dict()})
    seed = AdaptiveSolarCoordinator(hass, entry, site, template.client)
    populate(seed.shading, azimuth=90, elevation=20, factor=0.0)
    populate(seed.shading, azimuth=270, elevation=30, factor=0.5)
    populate(seed.shading, stage="j", azimuth=180, elevation=40, factor=1.0)
    with freeze_time(NOW, real_asyncio=True):
        stored = deepcopy(seed._stored())
        seed_store(seed._store, stored)
        await seed.async_close()
        await template.async_close()
        weather = await template.client.async_forecasts(NOW)
        with patch("custom_components.adaptive_solar.weather.OpenMeteoClient.async_forecasts",
                   new=AsyncMock(return_value=weather)):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
            try:
                instance = entry.runtime_data
                assert isinstance(instance, AdaptiveSolarCoordinator)
                for stage, expected in (("i", [(90, 20, 0.0), (270, 30, 0.5)]), ("j", [(180, 40, 1.0)])):
                    snapshot = instance.learner_status[stage]["beam_shade_windows"]
                    assert snapshot == instance.shading.window_diagnostics(stage, as_of=NOW)
                    assert snapshot["evaluated_at"] == NOW.isoformat()
                    assert [(item["azimuth_bin_deg"], item["elevation_bin_deg"], item["transmittance"])
                            for item in snapshot["items"]] == expected
                    assert snapshot["filled_bins"] == len(expected)
                # The real HA sensor state, not a hand-constructed attributes dict.
                quality_states = [state for state in hass.states.async_all("sensor") if "learning" in state.attributes]
                assert quality_states
                for state in quality_states:
                    assert state.attributes["learning"] == instance.learner_status
                assert "learning" in AdaptiveSolarSensor._unrecorded_attributes
                assert instance.shading.to_dict() == stored[BEAM_SHADE_STORE_KEY]
                assert instance._stored()["learning_feature_contract"] == stored["learning_feature_contract"]
                assert instance._stored()["shade_fingerprint"] == stored["shade_fingerprint"]
                first_snapshot = {stage: deepcopy(status["beam_shade_windows"])
                                  for stage, status in instance.learner_status.items()}
                assert await hass.config_entries.async_reload(entry.entry_id)
                await hass.async_block_till_done()
                assert {stage: status["beam_shade_windows"]
                        for stage, status in entry.runtime_data.learner_status.items()} == first_snapshot
                assert entry.runtime_data.shading.to_dict() == stored[BEAM_SHADE_STORE_KEY]
            finally:
                assert await hass.config_entries.async_unload(entry.entry_id)
                await hass.async_block_till_done()


async def test_current_store_roundtrip_diagnostics_preserve_learning_and_frozen_forecast_evidence(hass):
    instance, entry = coordinator(hass)
    with freeze_time(NOW + timedelta(hours=2), real_asyncio=True):
        await instance.async_restore()
        payload = evidence(instance)
        instance.archive = deepcopy(payload["archive"])
        instance.intervals = deepcopy(payload["intervals"])
        instance.daily_snapshots = deepcopy(payload["daily_snapshots"])
        populate(instance.shading)
        before = deepcopy(instance._stored())
        fit_inputs = join_training(instance.archive, instance.intervals, as_of=NOW + timedelta(hours=2))
        assert len(fit_inputs) == 2  # Both original NWP/GHI regimes really survive.
        snapshot = instance.shading.window_diagnostics("i", as_of=NOW + timedelta(hours=2))
        # Corrupting a display projection cannot rewrite any durable evidence.
        snapshot["items"][0]["transmittance"] = 0.0
        snapshot["policy"].clear()
        assert instance._stored() == before
        instance.async_commit_setup()
        await instance.async_close()
        restored, _ = coordinator(hass, entry)
        try:
            await restored.async_restore()
            assert restored._stored() == before
            assert restored.archive == payload["archive"]
            assert restored.intervals == payload["intervals"]
            assert restored.daily_snapshots == payload["daily_snapshots"]
            assert join_training(restored.archive, restored.intervals, as_of=NOW + timedelta(hours=2)) == fit_inputs
            item, = restored.shading.window_diagnostics("i", as_of=NOW + timedelta(hours=2))["items"]
            assert item["transmittance"] == 0.5 and item["released"] is True
            assert restored.shading.to_dict() == before[BEAM_SHADE_STORE_KEY]
        finally:
            await restored.async_close()


async def test_diagnostics_stay_out_of_exported_shade_decisions_and_replay_state(hass):
    instance, _ = make_coordinator(hass, enabled=True)
    populate(instance.shading)
    before = deepcopy(instance.shading.to_dict())
    with freeze_time(NOW, real_asyncio=True):
        try:
            await instance._async_update_data()
            instance.async_commit_setup()
            events = (await instance.export.page())["page"]["events"]
            issued, = [hydrate_forecast(event, events) for event in events if event["kind"] == "forecast_issued"]
            decision = issued["payload"]["shade_learning"]["decisions"]["i"]
            assert set(decision) == {
                "schema", "policy_version", "policy", "accepted", "reasons", "status", "input", "reference", "factor"}
            assert decision["status"] == instance.learner_status["i"]["beam_shade"]
            assert "beam_shade_windows" not in decision["status"]
            assert "items" not in decision["status"]
            state = decode_state(issued, events)
            assert state["shading_before"] == state["shading"] == before
            assert set(state["shading"]) == {"schema", "inverters", "released"}
            assert "beam_shade_windows" not in state
            assert "beam_shade_windows" not in issued["payload"]["result"]
            assert instance.learner_status["i"]["beam_shade_windows"]["total"] == 1
        finally:
            await instance.async_close()


async def test_display_projection_cannot_affect_forecast_training_or_fit_signature(hass):
    normal, _ = make_coordinator(hass)
    alternate, _ = make_coordinator(hass)
    populate(normal.shading)
    alternate.shading = normal.shading.copy()
    with freeze_time(NOW, real_asyncio=True):
        try:
            normal_result = await normal._async_update_data()
            # A deliberately unrelated display payload must not become model input.
            sentinel = {"schema_version": 999, "items": [{"transmittance": 0.123}], "display_only": True}
            with patch.object(BeamShadeTable, "window_diagnostics", return_value=deepcopy(sentinel)):
                alternate_result = await alternate._async_update_data()
            assert alternate.learner_status["i"]["beam_shade_windows"] == sentinel
            assert normal_result == alternate_result
            assert normal.archive == alternate.archive
            assert normal.intervals == alternate.intervals
            assert normal.shading.to_dict() == alternate.shading.to_dict()
            assert normal._fit_signature == alternate._fit_signature
            assert normal._training_snapshot == alternate._training_snapshot
            assert normal.learner_status["i"]["beam_shade"] == alternate.learner_status["i"]["beam_shade"]
        finally:
            await normal.async_close()
            await alternate.async_close()
