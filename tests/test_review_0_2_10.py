"""Regressions for restored observations and precise training rejection causes."""
from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock

from freezegun import freeze_time
from homeassistant.core import State
from pytest_homeassistant_custom_component.common import MockConfigEntry
import pytest

from custom_components.adaptive_solar.const import DOMAIN
from custom_components.adaptive_solar.coordinator import AdaptiveSolarCoordinator, join_training, state_number
from custom_components.adaptive_solar.core.engine import ForecastEngine
from custom_components.adaptive_solar.core.models import InverterConfig
from tests.test_irradiance import NOW, forecasts, site
from tests.test_training_alignment import NOW as TARGET, archived, measured


@pytest.mark.parametrize("kind,value,unit", [("power", 800, "W"), ("irradiance", 100, "W/m²"),
                                           ("temperature", -10, "°C"), ("wind", 15, "m/s"),
                                           ("energy", 12, "kWh")])
def test_restored_reports_are_rejected_for_every_sensor_class(kind, value, unit):
    with freeze_time(NOW):
        state = State("sensor.source", str(value), {"unit_of_measurement": unit, "restored": True})
        assert state_number(state, NOW, kind) is None
        genuine = State("sensor.source", str(value), {"unit_of_measurement": unit})
        assert state_number(genuine, NOW, kind) == value


@pytest.mark.parametrize("fresh", ["sensor.power", "sensor.ghi", "sensor.temperature", "sensor.wind"])
async def test_restored_inputs_leave_physics_unchanged_but_genuine_reports_apply(hass, fresh):
    cfg = replace(site(entity="sensor.ghi"), temperature_entity_id="sensor.temperature", wind_entity_id="sensor.wind",
                  inverters=(InverterConfig("i", 20, power_entity_id="sensor.power"),))
    entry = MockConfigEntry(domain=DOMAIN, data={"site": cfg.to_dict()})
    entry.add_to_hass(hass)
    coordinator = AdaptiveSolarCoordinator(hass, entry, cfg, AsyncMock())
    values = {"sensor.power": (800, "W"), "sensor.ghi": (100, "W/m²"),
              "sensor.temperature": (-10, "°C"), "sensor.wind": (15, "m/s")}
    with freeze_time(NOW):
        for entity, (value, unit) in values.items():
            hass.states.async_set(entity, str(value), {"unit_of_measurement": unit, "restored": True})
        engine = ForecastEngine(cfg)
        expected = [p.power_w for p in engine.forecast(forecasts(), NOW).points]
        restored = engine.forecast(forecasts(), NOW, coordinator._observations(NOW))
        assert [p.power_w for p in restored.points] == expected
        assert not coordinator._observations(NOW)
        value, unit = values[fresh]
        hass.states.async_set(fresh, str(value), {"unit_of_measurement": unit})
        genuine = engine.forecast(forecasts(), NOW, coordinator._observations(NOW))
        assert any(abs(a.power_w - b) > .01 for a, b in zip(genuine.points, expected, strict=True))
    await coordinator.async_close()


@pytest.mark.parametrize("reason", ["issued_after_target_start", "target_shorter_than_minimum", "source_partial_at_issue"])
def test_training_rejections_have_separate_reasons_without_relaxing_gates(reason):
    row = archived()
    if reason == "issued_after_target_start":
        row["issued_at"] = (TARGET + timedelta(seconds=1)).isoformat()
    elif reason == "target_shorter_than_minimum":
        row = archived(duration=900)
    else:
        row["features"]["source_partial_at_issue"] = 1
    quality = {}
    assert join_training([row], [measured()], diagnostics=quality) == []
    assert quality["i"]["rejection_reasons"] == {reason: 1}
    assert quality["i"]["rejected_target_cells"] == 1
