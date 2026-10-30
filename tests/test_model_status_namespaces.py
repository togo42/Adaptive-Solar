"""Arbitrary stage IDs cannot alias technical forecast diagnostics."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import json
from unittest.mock import AsyncMock
from urllib.parse import quote

from freezegun import freeze_time
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_solar.archive_export import json_value
from custom_components.adaptive_solar.coordinator import AdaptiveSolarCoordinator
from custom_components.adaptive_solar.core import engine as engine_module
from custom_components.adaptive_solar.core.engine import ForecastEngine
from custom_components.adaptive_solar.core.models import (
    ForecastPoint, ForecastResult, InverterConfig, Observation, SiteConfig, StringConfig,
)
from custom_components.adaptive_solar.core.physics import PhysicsUnavailable
from custom_components.adaptive_solar.core.replay import compare_results, replay_forecast, result_from_json
from custom_components.adaptive_solar.sensor import AdaptiveSolarSensor
from tests.test_cli import offline_process as offline_process
from tests.test_archive_replay import forecast_bundle
from tests.test_irradiance import NOW, START, forecasts, weather

PHYSICS_KEY = f"physics:a:i:{NOW.isoformat()}/{(START + timedelta(hours=1)).isoformat()}"


def site(ids=("irradiance",)):
    return SiteConfig(52, 13, "UTC", tuple(StringConfig(f"s{index}", inverter, 5, 30, 180)
        for index, inverter in enumerate(ids)), tuple(InverterConfig(inverter, 20) for inverter in ids),
        forecast_days=1, weather_models=("a",), irradiance_entity_id="sensor.ghi")


def source():
    return forecasts(points=[weather(START + timedelta(hours=hour)) for hour in range(14)])


@pytest.mark.parametrize("inverter_id", ["irradiance", "weather:a", "power_nowcast:i", PHYSICS_KEY])
def test_engine_preserves_exact_stage_and_diagnostic_status_for_colliding_ids(monkeypatch, inverter_id):
    config = site(("i", inverter_id))
    if inverter_id == PHYSICS_KEY:
        config = replace(config, physics_substeps=2)
        power = engine_module.interval_inverter_power

        def unavailable(*args, **kwargs):
            if kwargs.get("inverter_id") == "i" and kwargs.get("start") == NOW:
                raise PhysicsUnavailable("test_unavailable")
            return power(*args, **kwargs)

        monkeypatch.setattr(engine_module, "interval_inverter_power", unavailable)
    result = ForecastEngine(config).forecast(source(), NOW, (Observation(NOW, "i", power_w=1000, ghi_w_m2=800),))
    # This assertion demonstrates the original real status corruption before
    # inspecting the new canonical fields: diagnostic tokens leaked into it.
    assert result.model_status[inverter_id] == "physics"
    assert result.inverter_status[inverter_id] == "physics"
    assert result.diagnostic_status["irradiance"] == "usable:haurwitz_normalized"
    assert result.diagnostic_status["weather:a"] == "available"
    if inverter_id == "power_nowcast:i":
        assert result.diagnostic_status[inverter_id].startswith("usable:")
    elif inverter_id == PHYSICS_KEY:
        assert result.diagnostic_status[inverter_id] == "unavailable:test_unavailable"
    assert {point.inverter_id for point in result.points} == set(config_inverter.id for config_inverter in config.inverters)


@pytest.mark.parametrize("inverter_id", ["irradiance", "weather:a", "power_nowcast:i", PHYSICS_KEY])
async def test_native_ghi_quality_and_stage_status_are_independent_of_stage_id(hass, inverter_id):
    config = site((inverter_id,))
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    client = AsyncMock()
    client.errors = {}
    client.diagnostics = {}
    client.async_forecasts.return_value = source()
    instance = AdaptiveSolarCoordinator(hass, entry, config, client)
    with freeze_time(NOW, real_asyncio=True):
        hass.states.async_set("sensor.ghi", "800", {"unit_of_measurement": "W/m²"})
        instance.data = result = await instance._async_update_data()
        sensor = AdaptiveSolarSensor(instance, entry, None, "quality")
        assert sensor.native_value == "physics"
        assert instance.input_quality["irradiance_nowcast"] == "usable:haurwitz_normalized"
        attrs = sensor.extra_state_attributes
        assert attrs["coverage"] == "complete"
        assert attrs["inverter_status"] == result.inverter_status
        assert attrs["diagnostic_status"] == result.diagnostic_status
        published = attrs["learning_horizon"]["inverters"][inverter_id]["published_statuses"]
        assert not any(value.startswith(("usable:", "available", "unavailable:")) for value in published)
        assert {"inverter_status", "diagnostic_status"} <= sensor._unrecorded_attributes
        assert config.inverters[0].id == inverter_id
        await instance.async_close()


def test_forecast_result_positional_legacy_contract_and_canonical_json_roundtrip():
    point = ForecastPoint(NOW, NOW + timedelta(hours=1), "irradiance", 1000, 1000)
    old = ForecastResult(NOW, (point,), {"irradiance": "physics"}, {"a": (point,)}, {"a": NOW})
    assert old.inverter_status is old.diagnostic_status is None
    current = replace(old, inverter_status={"irradiance": "physics"},
                      diagnostic_status={"irradiance": "usable:haurwitz_normalized"})
    payload = json_value(current)
    assert result_from_json(payload) == current
    assert compare_results(current, result_from_json(payload))["matched"]
    legacy = json_value(old)
    legacy.pop("inverter_status")
    legacy.pop("diagnostic_status")
    original = deepcopy(legacy)
    restored = result_from_json(legacy)
    assert restored.inverter_status is restored.diagnostic_status is None
    assert compare_results(restored, current)["matched"]  # Existing exact flat-status contract.
    assert legacy == original
    assert not compare_results(restored, replace(current, model_status={"irradiance": "changed"}))["matched"]


@pytest.mark.parametrize("field", ["inverter_status", "diagnostic_status"])
def test_replay_checks_every_canonical_status_map_exactly(field):
    result = ForecastEngine(site()).forecast(source(), NOW, (Observation(NOW, "irradiance", ghi_w_m2=800),))
    changed = replace(result, **{field: {**getattr(result, field), "irradiance": "changed"}})
    assert not compare_results(result, changed)["matched"]
    assert compare_results(result, changed)["reason"] == "different_status_namespaces"
    legacy = replace(result, inverter_status=None, diagnostic_status=None)
    assert not compare_results(result, legacy)["matched"]


async def test_empty_canonical_maps_are_authoritative_for_sensor_and_coordinator(hass):
    config = site()
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    client = AsyncMock(errors={}, diagnostics={})
    client.async_forecasts.return_value = ()
    instance = AdaptiveSolarCoordinator(hass, entry, config, client)
    points = tuple(ForecastPoint(max(NOW, START + timedelta(hours=hour)), START + timedelta(hours=hour + 1),
        "irradiance", 1000, 1000) for hour in range(14))
    result = ForecastResult(NOW, points, {"irradiance": "usable:haurwitz_normalized;residual_no_uncertainty"},
                            inverter_status={}, diagnostic_status={})
    instance.engine.forecast = lambda *args, **kwargs: result
    with freeze_time(NOW, real_asyncio=True):
        hass.states.async_set("sensor.ghi", "800", {"unit_of_measurement": "W/m²"})
        instance.data = await instance._async_update_data()
        sensor = AdaptiveSolarSensor(instance, entry, None, "quality")
        assert instance.input_quality["irradiance_nowcast"] == "ignored:no_observation"
        assert sensor.native_value == "degraded"
        assert sensor.extra_state_attributes["learning_horizon"]["application"] == "physics"
        await instance.async_close()


def test_forecast_cli_exports_separate_status_maps_without_renaming_ids(offline_process, tmp_path):
    config = site(("irradiance", "weather:a", "power_nowcast:irradiance"))
    config_path, output = tmp_path / "site.json", tmp_path / "forecast.json"
    config_path.write_text(json.dumps(config.to_dict()))
    run = offline_process("forecast.py", "--config", config_path, "--synthetic", "--as-of", NOW.isoformat(), "--output", output)
    assert run.returncode == 0, run.stderr
    payload = json.loads(output.read_text())
    result = payload["forecast"]
    assert set(result["inverter_status"]) == {inverter.id for inverter in config.inverters}
    assert result["diagnostic_status"]["weather:a"] == "available"
    assert result["model_status"]["weather:a"] == result["inverter_status"]["weather:a"]
    assert set(payload["outputs"]) == {inverter.id for inverter in config.inverters}


def test_physics_diagnostic_id_segments_do_not_alias_between_models_and_stages(monkeypatch):
    config = replace(site(("c", "b:c")), physics_substeps=2, weather_models=("a", "a:b"))
    left = forecasts(model="a", points=[weather(ghi=100)])
    right = forecasts(model="a:b", points=[weather(ghi=200)])
    power = engine_module.interval_inverter_power

    def unavailable(config, point, **kwargs):
        if point.ghi_w_m2 == 100 and kwargs.get("inverter_id") == "b:c":
            raise PhysicsUnavailable("nonfinite_left")
        if point.ghi_w_m2 == 200 and kwargs.get("inverter_id") == "c":
            raise PhysicsUnavailable("nonfinite_right")
        return power(config, point, **kwargs)

    monkeypatch.setattr(engine_module, "interval_inverter_power", unavailable)
    result = ForecastEngine(config).forecast((*left, *right), NOW)
    interval = f"{NOW.isoformat()}/{(START + timedelta(hours=1)).isoformat()}"
    assert result.diagnostic_status[f"physics:a:b%3Ac:{interval}"] == "unavailable:nonfinite_left"
    assert result.diagnostic_status[f"physics:a%3Ab:c:{interval}"] == "unavailable:nonfinite_right"
    assert {point.inverter_id for point in result.points} == {"c", "b:c"}
    assert result.model_status[f"physics:a:b:c:{interval}"] in {
        "unavailable:nonfinite_left", "unavailable:nonfinite_right"}


def test_diagnostic_escaping_is_reversible_once_for_colon_percent_and_unicode_ids():
    ids = ("i:peer", "i%3Apeer", "i/peer", "Anlage Süd")
    models = ("a:b", "a%3Ab")
    config = replace(site(ids), weather_models=models)
    sources = tuple(forecast for model in models for forecast in forecasts(model=model))
    result = ForecastEngine(config).forecast(sources, NOW, tuple(Observation(NOW, inverter, power_w=1000) for inverter in ids))
    for model in models:
        assert result.diagnostic_status[f"weather:{quote(model, safe='')}"] == "available"
        assert result.model_status[f"weather:{model}"] == "available"
    for inverter in ids:
        assert result.diagnostic_status[f"power_nowcast:{quote(inverter, safe='')}"]
        assert result.model_status[f"power_nowcast:{inverter}"]
        assert result.inverter_status[inverter] == "physics"
    assert result_from_json(json_value(result)) == result


@pytest.mark.parametrize("field", ["inverter_status", "diagnostic_status"])
def test_original_archive_replay_rejects_changed_canonical_maps_without_flat_change(tmp_path, field):
    event, rows, _ = forecast_bundle(tmp_path)
    assert replay_forecast(event, rows)["baseline"]["accepted"]
    flat = deepcopy(event["payload"]["result"]["model_status"])
    event["payload"]["result"][field]["i"] = "changed"
    report = replay_forecast(event, rows)["baseline"]
    assert event["payload"]["result"]["model_status"] == flat
    assert report["reason"] == "different_status_namespaces"
    assert not report["matched"] and not report["accepted"]


def test_legacy_collided_status_is_not_silently_repaired_during_replay():
    current = ForecastEngine(site()).forecast(source(), NOW, (Observation(NOW, "irradiance", ghi_w_m2=800),))
    legacy = replace(current, model_status={**current.model_status, "irradiance": "physics;usable:haurwitz_normalized"},
                     inverter_status=None, diagnostic_status=None)
    assert compare_results(legacy, current)["reason"] == "different_model_status"
    assert not compare_results(legacy, current)["matched"]
