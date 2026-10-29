"""Frozen display curves retain original energy, issue time and persistence boundaries."""
from copy import deepcopy
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

from freezegun import freeze_time
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_solar.coordinator import AdaptiveSolarCoordinator
from custom_components.adaptive_solar.core.models import ForecastPoint, ForecastResult, InverterConfig, SiteConfig, StringConfig
from custom_components.adaptive_solar.sensor import AdaptiveSolarSensor, day_bounds
from custom_components.adaptive_solar.snapshots import make_snapshot, provenance, snapshot_curve, validate_snapshot


def site():
    return SiteConfig(52, 13, "Europe/Berlin", (StringConfig("s0", "i0", 5, 30, 180),
                      StringConfig("s1", "i1", 5, 30, 180)), (InverterConfig("i0", 5), InverterConfig("i1", 5)))


def forecast(config, day):
    start, end = day_bounds(datetime.fromisoformat(day + "T12:00:00+00:00"), config.timezone, 0)
    # Split source intervals prove the snapshot integrates native interval
    # energy, preserving a genuine zero cell and arbitrary source boundaries.
    points = []
    for inv, power in [("i0", 1234.56789), ("i1", 678.12345)]:
        cursor = start
        while cursor < end:
            stop = min(cursor + timedelta(minutes=30), end)
            watts = 0 if cursor < start + timedelta(hours=1) else power
            points.append(ForecastPoint(cursor, stop, inv, watts, watts))
            cursor = stop
    return start, end, ForecastResult(start - timedelta(minutes=5), tuple(points))


@pytest.mark.parametrize("day,hours", [("2026-03-29", 23), ("2026-06-01", 24), ("2026-10-25", 25)])
def test_native_curve_covers_true_local_day_and_matches_daily_total(day, hours):
    config = site()
    start, end, result = forecast(config, day)
    snapshot = make_snapshot(result, start, end, config)
    clean, _ = validate_snapshot(day, snapshot, provenance(config), config)
    for inv in config.inverters:
        curve = snapshot_curve(clean, [inv.id])
        assert len(curve) == hours
        assert curve[0] == {"start": start.isoformat(), "end": (start + timedelta(hours=1)).isoformat(), "energy_kwh": 0}
        assert curve[-1]["end"] == end.isoformat()
        assert sum(p["energy_kwh"] for p in curve) == pytest.approx(snapshot["energies"][inv.id])
    total = snapshot_curve(clean, ["i0", "i1"])
    assert sum(p["energy_kwh"] for p in total) == pytest.approx(sum(snapshot["energies"].values()))
    if hours == 25:
        assert total[2]["start"] != total[3]["start"]  # both local 02:00 folds


def test_incomplete_forecast_cannot_create_a_full_day_curve():
    config = site()
    start, end, result = forecast(config, "2026-06-01")
    assert make_snapshot(ForecastResult(result.issued_at, result.points[1:]), start, end, config) is None


@pytest.mark.parametrize("damage", ["gap", "overlap", "sum", "bool", "nan", "stages", "oversize", "naive", "type"])
def test_optional_curve_corruption_does_not_erase_original_daily_totals(damage):
    config = site()
    start, end, result = forecast(config, "2026-06-01")
    snapshot = make_snapshot(result, start, end, config)
    broken = deepcopy(snapshot)
    curve = broken["forecast"]["i0"]
    if damage == "gap":
        curve.pop(2)
    elif damage == "overlap":
        curve[2] = curve[1]
    elif damage == "sum":
        curve[2]["energy_kwh"] += .1
    elif damage == "bool":
        curve[2]["energy_kwh"] = True
    elif damage == "nan":
        curve[2]["energy_kwh"] = float("nan")
    elif damage == "stages":
        broken["forecast"].pop("i1")
    elif damage == "oversize":
        curve.extend(deepcopy(curve))
    elif damage == "naive":
        curve[0]["start"] = "2026-05-31T22:00:00"
    else:
        curve[0]["start"] = None
    with pytest.raises(ValueError, match="invalid day-start curve"):
        validate_snapshot("2026-06-01", broken, provenance(config), config)
    clean, _ = validate_snapshot("2026-06-01", broken, provenance(config), config, strict_curve=False)
    assert clean == {"issued_at": snapshot["issued_at"], "energies": snapshot["energies"]}


async def test_curve_survives_real_store_reload_and_later_runs_without_changing_rest(hass):
    config = site()
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    start, end, result = forecast(config, "2026-10-25")
    with freeze_time(start - timedelta(minutes=5)):
        coordinator = AdaptiveSolarCoordinator(hass, entry, config, AsyncMock())
        await coordinator.async_restore()
        coordinator._archive_result(result, available_at=result.issued_at)
        saved = deepcopy(coordinator.daily_snapshots["2026-10-25"])
        stored = coordinator._stored()
        assert stored["daily_snapshots"]["2026-10-25"] == {
            "issued_at": saved["issued_at"], "energies": saved["energies"]}
        assert stored["daily_snapshot_curves"]["2026-10-25"] == saved["forecast"]
        coordinator.async_commit_setup()
        await coordinator.async_close()

    with freeze_time(start + timedelta(hours=12)):
        restored = AdaptiveSolarCoordinator(hass, entry, config, AsyncMock())
        await restored.async_restore()
        later = ForecastResult(start + timedelta(hours=12), tuple(ForecastPoint(
            p.start, p.end, p.inverter_id, 2000, 2000) for p in result.points if p.start >= start + timedelta(hours=12)))
        restored.data = later
        restored._archive_result(later, available_at=later.issued_at)
        assert restored.daily_snapshots["2026-10-25"] == saved
        for inv in [None, "i0"]:
            sensor = AdaptiveSolarSensor(restored, entry, inv, "day", 0)
            attrs = sensor.extra_state_attributes
            assert attrs["forecast_curve_status"] == "available"
            assert attrs["issued_at"] == result.issued_at.isoformat()
            assert len(attrs["forecast"]) == 25
            assert sum(p["energy_kwh"] for p in attrs["forecast"]) == pytest.approx(sensor.native_value)
        remaining = AdaptiveSolarSensor(restored, entry, "i0", "remaining")
        assert remaining.native_value == pytest.approx(26)  # 13 remaining real hours at 2 kW
        await restored.async_close()


async def test_legacy_total_survives_without_fabricating_curve_or_resetting_state(hass):
    config = site()
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    start, end, result = forecast(config, "2026-06-01")
    snapshot = make_snapshot(result, start, end, config)
    snapshot.pop("forecast")
    with freeze_time(start + timedelta(hours=12)):
        coordinator = AdaptiveSolarCoordinator(hass, entry, config, AsyncMock())
        coordinator._restore_snapshots({"daily_snapshots": {"2026-06-01": snapshot},
                                        "daily_snapshot_provenance": {"2026-06-01": provenance(config)}}, same_history=True)
        coordinator.data = result
        sensor = AdaptiveSolarSensor(coordinator, entry, "i0", "day", 0)
        assert sensor.native_value == snapshot["energies"]["i0"]
        assert sensor.extra_state_attributes["forecast"] == []
        assert sensor.extra_state_attributes["forecast_curve_status"] == "not_stored"
        # A valid snapshot from another configuration keeps its own original
        # caps/provenance, as before; adding curves never forces re-learning.
        await coordinator.async_close()


@pytest.mark.parametrize("curves", [None, [], {"2026-06-01": {"i0": []}}, {str(i): {} for i in range(33)}])
async def test_corrupt_optional_store_sibling_preserves_legacy_snapshot(hass, curves):
    config = site()
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    start, end, result = forecast(config, "2026-06-01")
    legacy = make_snapshot(result, start, end, config)
    legacy.pop("forecast")
    with freeze_time(start + timedelta(hours=12)):
        coordinator = AdaptiveSolarCoordinator(hass, entry, config, AsyncMock())
        coordinator._restore_snapshots({"daily_snapshots": {"2026-06-01": legacy},
            "daily_snapshot_provenance": {"2026-06-01": provenance(config)},
            "daily_snapshot_curves": curves}, same_history=True)
        assert coordinator.daily_snapshots == {"2026-06-01": legacy}
        await coordinator.async_close()
