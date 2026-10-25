"""Native Wh are complete UTC hours; current partial energy keeps its duration."""
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

from freezegun import freeze_time
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_solar.const import DOMAIN
from custom_components.adaptive_solar.core.models import ForecastPoint, ForecastResult, InverterConfig, SiteConfig, StringConfig
from custom_components.adaptive_solar.energy import async_get_solar_forecast
from custom_components.adaptive_solar.sensor import AdaptiveSolarSensor, day_bounds

START = datetime(2026, 6, 1, 10, tzinfo=UTC)


def setup_forecast(hass, points, issued, two=False):
    inverters = tuple(InverterConfig(f"i{index}", 5) for index in range(2 if two else 1))
    site = SiteConfig(52, 13, "Europe/Berlin",
                      tuple(StringConfig(f"s{index}", inv.id, 5, 30, 180) for index, inv in enumerate(inverters)),
                      inverters)
    entry = MockConfigEntry(domain=DOMAIN, data={"site": site.to_dict()})
    entry.add_to_hass(hass)
    entry.runtime_data = Mock(site=site, data=ForecastResult(issued, tuple(points)), last_update_success=True,
                              input_quality={}, learner_status={}, archive=[], intervals=[], client=Mock(errors={}))
    return entry


def point(start, end, power, inverter="i0"):
    return ForecastPoint(start, end, inverter, power, power)


async def test_current_partial_energy_matches_remaining_and_quality_but_is_not_a_full_native_hour(hass):
    issued = START + timedelta(minutes=50)
    points = [point(issued, START + timedelta(hours=1), 1200),
              point(START + timedelta(hours=1), START + timedelta(hours=1, minutes=15), 400),
              point(START + timedelta(hours=1, minutes=15), START + timedelta(hours=2), 800)]
    points.extend(point(START + timedelta(hours=hour), START + timedelta(hours=hour + 1), 0)
                  for hour in range(2, 12))  # Known synthetic zeros through local midnight.
    entry = setup_forecast(hass, points, issued)
    result = entry.runtime_data.data
    assert result.power_at(issued - timedelta(seconds=1), "i0") is None
    assert result.power_at(issued, "i0") == 1200
    assert result.energy_kwh(issued, START + timedelta(hours=2), "i0") == pytest.approx(.9)
    with freeze_time(issued):
        remaining = AdaptiveSolarSensor(entry.runtime_data, entry, None, "remaining")
        quality = AdaptiveSolarSensor(entry.runtime_data, entry, None, "quality")
        assert remaining.native_value == pytest.approx(.9)
        curve = quality.extra_state_attributes["forecast"]
        assert curve[0]["start"] == issued.isoformat()
        assert curve[0]["energy_kwh"] == pytest.approx(.2)
        assert sum(row["energy_kwh"] for row in curve) == pytest.approx(.9)
    native = (await async_get_solar_forecast(hass, entry.entry_id))["wh_hours"]
    assert START.isoformat() not in native and issued.isoformat() not in native
    assert native[(START + timedelta(hours=1)).isoformat()] == pytest.approx(700)
    assert all(datetime.fromisoformat(key).minute == 0 for key in native)


async def test_native_hour_aggregates_smaller_cells_and_requires_every_inverter(hass):
    end = START + timedelta(hours=1)
    points = [point(START + timedelta(minutes=15 * index), START + timedelta(minutes=15 * (index + 1)), 1000)
              for index in range(4)]
    entry = setup_forecast(hass, points, START, two=True)
    assert await async_get_solar_forecast(hass, entry.entry_id) is None
    entry.runtime_data.data = ForecastResult(START, (*points, point(START, end, 2000, "i1")))
    assert (await async_get_solar_forecast(hass, entry.entry_id))["wh_hours"] == {START.isoformat(): 3000}
    entry.runtime_data.data = ForecastResult(START, (*points[:-1], point(START, end, 2000, "i1")))
    assert await async_get_solar_forecast(hass, entry.entry_id) is None


@pytest.mark.parametrize("day,hours", [(datetime(2026, 3, 29, tzinfo=UTC), 23),
                                      (datetime(2026, 10, 25, tzinfo=UTC), 25)])
async def test_native_energy_keeps_distinct_utc_hours_on_both_local_dst_days(hass, day, hours):
    start, end = day_bounds(day, "Europe/Berlin", 0)
    points = [point(start + timedelta(hours=index), start + timedelta(hours=index + 1), 1000)
              for index in range(hours)]
    entry = setup_forecast(hass, points, start)
    native = (await async_get_solar_forecast(hass, entry.entry_id))["wh_hours"]
    assert len(native) == hours and sum(native.values()) == 1000 * hours
    assert entry.runtime_data.data.energy_kwh(start, end, "i0") == hours
