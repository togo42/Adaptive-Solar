"""Native HA export lifecycle, authenticated service and immutable replay receipts."""
from datetime import UTC, datetime, timedelta
import json
import base64
import zlib
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from freezegun import freeze_time
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError, Unauthorized
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
import voluptuous as vol

from custom_components.adaptive_solar import services
from custom_components.adaptive_solar.archive_export import ArchiveExport, encoded, replay_events
from custom_components.adaptive_solar.coordinator import AdaptiveSolarCoordinator
from custom_components.adaptive_solar.core.archive import ArchiveJournal
from custom_components.adaptive_solar.core.models import InverterConfig, SiteConfig, StringConfig, WeatherForecast, WeatherPoint

NOW = datetime(2026, 6, 1, 10, tzinfo=UTC)


@pytest.fixture(autouse=True)
def private_config_directory(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)


def make_coordinator(hass, enabled=False):
    site = SiteConfig(52, 13, "UTC", (StringConfig("s", "i", 5, 30, 180),), (InverterConfig("i", 5),))
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": site.to_dict()}, options={"archive_export": enabled})
    entry.add_to_hass(hass)
    weather = WeatherForecast("best_match", NOW, tuple(WeatherPoint(NOW + timedelta(hours=h), NOW + timedelta(hours=h+1),
        600 if h < 8 else 0, 400 if h < 8 else 0, 200 if h < 8 else 0, 20, 2, 30) for h in range(16)))
    client = SimpleNamespace(async_forecasts=AsyncMock(return_value=(weather,)), errors={}, receipt_ids={"best_match": "source-id"})
    return AdaptiveSolarCoordinator(hass, entry, site, client), entry


async def test_disabled_default_never_creates_files_or_serializes(hass):
    instance, _ = make_coordinator(hass)
    with freeze_time(NOW, real_asyncio=True), patch("custom_components.adaptive_solar.coordinator.replay_events", side_effect=AssertionError):
        result = await instance._async_update_data()
        assert result.points
        instance.async_commit_setup()
        assert await instance.export.page() == {"page": None, "status": instance.export.status}
        await instance.async_close()
    assert not Path(instance.export.root).exists()


async def test_enabled_forecast_parity_all_issued_cells_and_restart(hass):
    enabled, _ = make_coordinator(hass, True)
    disabled, _ = make_coordinator(hass)
    with freeze_time(NOW, real_asyncio=True):
        assert await enabled._async_update_data() == await disabled._async_update_data()
        assert not Path(enabled.export.root).exists()  # failed setup cannot write
        enabled.async_commit_setup()
        response = await enabled.export.page()
        events = response["page"]["events"]
        issued = next(event["payload"] for event in events if event["kind"] == "forecast_issued")
        chunks = [event["payload"] for event in events if event["kind"] == "forecast_state_chunk"]
        state = json.loads(zlib.decompress(base64.b64decode("".join(chunk["data_fragment"] for chunk in sorted(chunks, key=lambda x: x["index"])))))
        assert issued["result"]["points"] == json.loads(encoded(enabled.data or await enabled._async_update_data()))["points"]
        assert len(issued["result"]["points"]) > len(enabled.archive)  # includes night
        assert issued["weather_receipt_ids"] == {"best_match": "source-id"}
        assert state["fit_as_of"] == NOW.isoformat() and state["fit_samples"] == []
        assert issued["software"]["libraries"]["homeassistant"]
        assert issued["software"]["source_sha256"]
        generation = response["page"]["generation"]
        await enabled.async_close()
        restarted = ArchiveExport(hass, enabled.config_entry.entry_id, enabled=True)
        restored = await restarted.page()
        assert restored["page"]["generation"] == generation
        assert restored["page"]["events"]
        await restarted.close()
        await disabled.async_close()


async def test_failed_setup_discards_pending_without_disk_write(hass):
    instance, _ = make_coordinator(hass, True)
    with freeze_time(NOW, real_asyncio=True):
        await instance._async_update_data()
        await instance.async_close()
    assert not Path(instance.export.root).exists()
    assert not instance.export.status["pending_events"]


async def test_archive_disk_failure_does_not_change_forecast(hass):
    instance, _ = make_coordinator(hass, True)
    with freeze_time(NOW, real_asyncio=True), patch.object(ArchiveJournal, "append_many", side_effect=OSError("private path")):
        instance.async_commit_setup()
        result = await instance._async_update_data()
        await instance.export.page()
        assert result.points
        assert instance.export.status["state"] == "error"
        assert instance.export.status["last_error"] == "OSError"
        assert "private path" not in str(instance.export.status)
        await instance.async_close()


async def test_serialization_failure_does_not_change_forecast(hass):
    instance, _ = make_coordinator(hass, True)
    with freeze_time(NOW, real_asyncio=True), patch("custom_components.adaptive_solar.coordinator.replay_events", side_effect=ValueError("broken")):
        result = await instance._async_update_data()
        assert result.points
        assert instance.export.status["state"] == "error"
        await instance.async_close()


async def test_pending_queue_both_byte_and_event_bounds_are_visible(hass):
    export = ArchiveExport(hass, "bounded", enabled=True)
    with patch("custom_components.adaptive_solar.archive_export.MAX_PENDING_EVENTS", 2):
        for _ in range(3):
            export.record("source_report", {}, NOW)
    assert export.status["pending_events"] == 2
    assert export.status["dropped_events"] == 1
    with patch("custom_components.adaptive_solar.archive_export.MAX_PENDING_BYTES", 10):
        export.record("source_report", {"long": "x" * 100}, NOW)
    assert export.status["dropped_events"] == 2
    assert export.status["state"] == "gap"
    await export.close()


def test_large_state_chunks_reassemble_and_references_repeat_with_ttl():
    state = {"rows": [{"data": sha256(str(index).encode()).hexdigest()} for index in range(20_000)]}
    first = replay_events({"result": {}}, state, NOW)
    second = replay_events({"result": {}}, state, NOW + timedelta(hours=73))
    chunks = [json.loads(text) for kind, text, *_ in first if kind == "forecast_state_chunk"]
    assert len(chunks) > 1
    assert json.loads(zlib.decompress(base64.b64decode("".join(chunk["data_fragment"] for chunk in chunks)))) == state
    assert json.loads(first[-1][1])["replay_state"]["event_ids"] != json.loads(second[-1][1])["replay_state"]["event_ids"]


async def export_call(hass, data, context=None):
    return await hass.services.async_call("adaptive_solar", services.EXPORT_SERVICE, data,
                                         blocking=True, return_response=True, context=context)


async def test_native_admin_export_service_schema_auth_and_ownership(hass, hass_admin_user):
    export = ArchiveExport(hass, "service", enabled=True)
    export.record("test", {"value": 1}, NOW)
    export.activate()
    services.async_register_reference_service(hass, "owner-a")
    services.async_register_reference_service(hass, "owner-b")
    entry = SimpleNamespace(domain="adaptive_solar", state=ConfigEntryState.LOADED,
                            runtime_data=SimpleNamespace(export=export))
    with patch.object(hass.config_entries, "async_get_entry", return_value=entry):
        response = await export_call(hass, {"config_entry_id": "owner-a"})
        assert response["page"]["events"][0]["payload"] == {"value": 1}
        nonadmin = await hass.auth.async_create_user("Reader", group_ids=["system-users"])
        with pytest.raises(Unauthorized):
            await export_call(hass, {"config_entry_id": "owner-a"}, Context(user_id=nonadmin.id))
        for extra in ({"cursor": "bad"}, {"limit": 0}, {"limit": 1001}, {"limit": True}, {"max_bytes": 5},
                      {"generation": "wrong", "cursor": "also-wrong:0"}, {"unexpected": 1}):
            with pytest.raises((vol.Invalid, HomeAssistantError)):
                await export_call(hass, {"config_entry_id": "owner-a", **extra})
    services.async_unregister_reference_service(hass, "owner-a")
    assert hass.services.has_service("adaptive_solar", services.EXPORT_SERVICE)
    services.async_unregister_reference_service(hass, "owner-b")
    assert not hass.services.has_service("adaptive_solar", services.EXPORT_SERVICE)
    await export.close()


async def test_state_dedup_reuses_only_retained_chunks_and_refreshes_after_ttl(hass):
    export = ArchiveExport(hass, "dedup", enabled=True)
    state = {"fit_samples": [], "shading": {}}
    export.submit(replay_events({"result": {}}, state, NOW))
    export.activate()
    first = (await export.page())["page"]
    export.submit(replay_events({"result": {}}, state, NOW + timedelta(minutes=5)))
    second = (await export.page())["page"]
    assert len([event for event in second["events"] if event["kind"] == "forecast_state_chunk"]) == 1
    forecasts = [event for event in second["events"] if event["kind"] == "forecast_issued"]
    assert forecasts[0]["payload"]["replay_state"] == forecasts[1]["payload"]["replay_state"]
    export.submit(replay_events({"result": {}}, state, NOW + timedelta(hours=73)))
    third = (await export.page())["page"]
    latest = next(event for event in reversed(third["events"]) if event["kind"] == "forecast_issued")
    ref = latest["payload"]["replay_state"]
    assert ref != first["events"][-1]["payload"]["replay_state"]
    assert set(ref["event_ids"]) <= {event["event_id"] for event in third["events"]}
    await export.close()


def test_sixty_thousand_training_rows_fit_bounded_compressed_bundle():
    rows = [{"issued_at": (NOW + timedelta(minutes=index)).isoformat(),
             "start": (NOW + timedelta(hours=index // 12)).isoformat(),
             "inverter_id": "synthetic_stage", "baseline_w": index * 0.04,
             "actual_w": index * 0.041,
             "features": {f"feature_{feature}": (index % 997) * 0.01 + feature for feature in range(25)}}
            for index in range(60_000)]
    events = replay_events({"result": {}}, {"fit_samples": rows}, NOW)
    assert len(events) < 64
    assert sum(len(event[1]) for event in events) < 8 * 1024 * 1024
    assert json.loads(events[-1][1])["replay_state"]["uncompressed_bytes"] > 32 * 1024 * 1024


@pytest.mark.parametrize("platform_failure", [False, True])
async def test_native_entry_setup_only_commits_export_after_platform_success(hass, enable_custom_integrations, platform_failure):
    instance, entry = make_coordinator(hass, True)
    weather = instance.client.async_forecasts.return_value
    with freeze_time(NOW, real_asyncio=True), patch(
            "custom_components.adaptive_solar.weather.OpenMeteoClient.async_forecasts",
            new=AsyncMock(return_value=weather)):
        if platform_failure:
            with patch.object(hass.config_entries, "async_forward_entry_setups", side_effect=RuntimeError("platform failed")):
                assert not await hass.config_entries.async_setup(entry.entry_id)
            assert not Path(instance.export.root).exists()
            assert not hass.services.has_service("adaptive_solar", services.EXPORT_SERVICE)
        else:
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
            response = await export_call(hass, {"config_entry_id": entry.entry_id})
            assert response["page"]["events"]
            assert await hass.config_entries.async_unload(entry.entry_id)
            assert not hass.services.has_service("adaptive_solar", services.EXPORT_SERVICE)
    await instance.async_close()


async def test_week_four_stages_three_models_chunk_full_payload_and_replay(hass):
    """A valid site exceeds the journal event cap before compression/chunking."""
    from custom_components.adaptive_solar.core.archive import MAX_EVENT_BYTES, canonical_bytes
    from custom_components.adaptive_solar.core.replay import hydrate_forecast, replay_forecast
    from custom_components.adaptive_solar.weather import UNITS, VARIABLES, parse_forecast

    models = ("best_match", "icon_d2", "ecmwf_ifs025")
    site = SiteConfig(52, 13, "UTC",
                      tuple(StringConfig(f"s{index}", f"i{index}", 5, 30, 180) for index in range(4)),
                      tuple(InverterConfig(f"i{index}", 5) for index in range(4)),
                      weather_models=models, forecast_days=7)
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": site.to_dict()}, options={"archive_export": True})
    entry.add_to_hass(hass)
    raw = {"hourly_units": dict(UNITS), "hourly": {
        "time": [(NOW - timedelta(hours=1) + timedelta(hours=index)).timestamp() for index in range(170)],
        **{key: [value] * 170 for key, value in zip(VARIABLES, [600, 400, 200, 20, 2, 30], strict=True)},
    }}
    forecasts = tuple(parse_forecast(raw, model, NOW, site) for model in models)
    receipt_ids = {model: f"weather-{model}" for model in models}
    client = SimpleNamespace(async_forecasts=AsyncMock(return_value=forecasts), errors={}, receipt_ids=receipt_ids)
    instance = AdaptiveSolarCoordinator(hass, entry, site, client)
    for model in models:
        instance.export.record("weather_response", {"model": model, "status": "available", "raw_response": raw},
                               NOW, receipt_ids[model])
    with freeze_time(NOW, real_asyncio=True):
        original = await instance._async_update_data()
        instance.async_commit_setup()
        events = (await instance.export.page())["page"]["events"]
        assert instance.export.status["last_error"] is None
        assert all(len(canonical_bytes(event)) <= MAX_EVENT_BYTES for event in events)
        issued = next(event for event in events if event["kind"] == "forecast_issued")
        assert "payload_ref" in issued["payload"]
        hydrated = hydrate_forecast(issued, events)
        assert len(encoded(hydrated["payload"]).encode()) > MAX_EVENT_BYTES
        assert hydrated["payload"]["result"] == json.loads(encoded(original))
        assert len(hydrated["payload"]["weather"]) == 3
        assert len(hydrated["payload"]["individual_model_physics"]) == 3
        replayed = replay_forecast(issued, events)
        assert replayed["baseline"]["matched"]
        assert replayed["outputs"]["baseline"] == original
        # Repeated large forecasts cannot reuse state references embedded in a
        # compressed payload unless the full payload is rebuilt accordingly.
        await instance._async_update_data()
        repeated = (await instance.export.page())["page"]["events"]
        latest = next(event for event in reversed(repeated) if event["kind"] == "forecast_issued")
        assert replay_forecast(latest, repeated)["baseline"]["matched"]
        await instance.async_close()


async def test_large_original_weather_response_keeps_receipt_id_and_raw_payload(hass):
    from custom_components.adaptive_solar.core.archive import MAX_EVENT_BYTES, canonical_bytes
    from custom_components.adaptive_solar.core.replay import hydrate_weather

    raw = {"model": "synthetic", "status": "available", "raw_response": {
        "opaque_provider_metadata": "".join(sha256(str(index).encode()).hexdigest() for index in range(25_000))}}
    export = ArchiveExport(hass, "large-weather", enabled=True)
    export.record("weather_response", raw, NOW, "original-receipt-id")
    export.activate()
    events = (await export.page())["page"]["events"]
    assert export.status["last_error"] is None
    assert all(len(canonical_bytes(event)) <= MAX_EVENT_BYTES for event in events)
    manifest = next(event for event in events if event["kind"] == "weather_response")
    assert manifest["event_id"] == "original-receipt-id"
    assert "payload_ref" in manifest["payload"]
    assert len(manifest["payload"]["payload_ref"]["event_ids"]) > 1
    assert hydrate_weather(manifest, events)["payload"] == raw
    await export.close()


async def test_failed_late_batch_record_preserves_journal_and_state_cache(hass):
    export = ArchiveExport(hass, "atomic-batch", enabled=True)
    export.journal = await hass.async_add_executor_job(lambda: ArchiveJournal(export.root, max_event_bytes=2048))
    events = replay_events({"result": {}}, {"fit_samples": [], "shading": {}}, NOW)
    # The chunk and forecast fit individually; the final bad item must prevent
    # even those preceding valid records and cache references from committing.
    events.append(("source_report", encoded({"oversize": "x" * 4096}), NOW, "bad-tail"))
    export.submit(events)
    export.activate()
    response = await export.page()
    assert response["page"]["events"] == []
    assert response["page"]["next_cursor"].endswith(":0")
    assert response["status"]["state"] == "error"
    assert export._state_cache == {}
    assert export._reported_drops == 0
    await export.close()


async def test_fit_failure_and_recovery_export_exact_optional_learner_state(hass):
    from custom_components.adaptive_solar.core.learning import ResidualLearner
    from custom_components.adaptive_solar.core.replay import reconstruct_state, replay_forecast
    from custom_components.adaptive_solar.weather import parse_forecast
    from tests.test_weather import payload

    instance, _ = make_coordinator(hass, True)
    raw = payload(start=NOW - timedelta(hours=1), count=8)
    weather = parse_forecast(raw, "best_match", NOW, instance.site)
    instance.client.async_forecasts.return_value = (weather,)
    instance.client.receipt_ids = {"best_match": "original-weather"}
    with freeze_time(NOW, real_asyncio=True):
        instance.export.record("weather_response", {"model": "best_match", "status": "available", "raw_response": raw},
                               NOW, "original-weather")
        with patch.object(ResidualLearner, "fit", side_effect=RuntimeError("optional failure")):
            failed = await instance._async_update_data()
        recovered = await instance._async_update_data()
        assert failed.points and recovered.points
        instance.async_commit_setup()
        events = (await instance.export.page())["page"]["events"]
        issued = [event for event in events if event["kind"] == "forecast_issued"]
        unavailable, available = [reconstruct_state(event, events) for event in issued]
        assert unavailable["learner_available"] is False
        assert unavailable["fit_samples"] == [] and unavailable["fit_as_of"] is None
        assert available["learner_available"] is True
        assert available["fit_as_of"] == NOW.isoformat()
        for event in issued:
            assert replay_forecast(event, events)["baseline"]["accepted"]
            assert event["payload"]["early_bias_shadow"]["status"]["operational_use"] is False
        await instance.async_close()


async def test_archive_availability_includes_serialization_after_computation(hass):
    from custom_components.adaptive_solar.core.replay import replay_forecast

    instance, _ = make_coordinator(hass, True)
    original = replay_events
    with freeze_time(NOW, real_asyncio=True) as clock:
        def encode_then_advance(*args, **kwargs):
            events = original(*args, **kwargs)
            clock.tick(timedelta(seconds=20))
            return events

        with patch("custom_components.adaptive_solar.coordinator.replay_events", side_effect=encode_then_advance):
            await instance._async_update_data()
        instance.async_commit_setup()
        events = (await instance.export.page())["page"]["events"]
        issued = next(event for event in events if event["kind"] == "forecast_issued")
        assert issued["payload"]["issued_at"] == NOW.isoformat()
        assert issued["payload"]["computed_at"] == NOW.isoformat()
        assert issued["received_at"] == (NOW + timedelta(seconds=20)).isoformat()
        assert all(event["received_at"] == issued["received_at"] for event in events)
        with pytest.raises(ValueError, match="not archived.*as-of"):
            replay_forecast(issued, events, as_of=NOW + timedelta(seconds=10))
        await instance.async_close()


async def test_original_interval_binds_source_without_changing_learning_payload(hass):
    from dataclasses import replace
    from homeassistant.core import State
    from custom_components.adaptive_solar.core.actual_quality import digest

    instance, _ = make_coordinator(hass, True)
    inv = replace(instance.site.inverters[0], energy_entity_id="sensor.original_energy")
    instance.site = replace(instance.site, inverters=(inv,))
    with freeze_time(NOW, real_asyncio=True):
        await instance._async_update_data()
        instance.async_commit_setup()
        for offset, energy in ((0, "1"), (5, "1.1"), (10, "1.2")):
            stamp = NOW + timedelta(minutes=offset)
            state = State(inv.energy_entity_id, energy, {"unit_of_measurement": "kWh"}, last_updated=stamp)
            instance._record_energy(inv, state, stamp, reported_at=stamp)
        response = await instance.export.page()
        originals = [event["payload"] for event in response["page"]["events"] if event["kind"] == "qualified_interval"]
        assert len(originals) == 2
        assert all(p["source_binding"] == {"schema": 1, "energy_entity_id": inv.energy_entity_id,
                   "config_sha256": digest(instance.site.to_dict()),
                   "producer_sha256": instance._export_software["source_sha256"]} for p in originals)
        assert all("source_binding" not in p for p in instance.intervals)
        await instance.async_close()


async def test_provenance_read_failure_does_not_block_forecast(hass):
    instance, _ = make_coordinator(hass, True)
    with freeze_time(NOW, real_asyncio=True), patch(
            "custom_components.adaptive_solar.coordinator.software_provenance", side_effect=OSError):
        result = await instance._async_update_data()
        assert result.points
        assert instance._export_software is None
        await instance.async_close()
