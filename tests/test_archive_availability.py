"""Executor completion bounds day-start snapshots and prospective training."""
import asyncio
from copy import deepcopy
from datetime import UTC, datetime, time, timedelta
import threading
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from freezegun import freeze_time
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_solar.coordinator import AdaptiveSolarCoordinator
from custom_components.adaptive_solar.core.models import (
    ForecastPoint, ForecastResult, InverterConfig, SiteConfig, StringConfig,
)


def instance_and_points(hass, target_day):
    zone = ZoneInfo("Europe/Berlin")
    day = datetime.fromisoformat(target_day).date()
    start = datetime.combine(day, time(), zone).astimezone(UTC)
    next_day = datetime.combine(day + timedelta(days=1), time(), zone).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=2), time(), zone).astimezone(UTC)
    config = SiteConfig(52, 13, zone.key, (StringConfig("s", "i", 5, 30, 180),), (InverterConfig("i", 5),), forecast_days=3)
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    client = AsyncMock()
    client.async_forecasts.return_value = ()
    instance = AdaptiveSolarCoordinator(hass, entry, config, client)
    # Synthetic whole-cell forecast isolates archive chronology from nighttime
    # solar physics. Every target remains eligible under the feature contract.
    points = []
    cursor = start
    while cursor < end:
        points.append(ForecastPoint(cursor, cursor + timedelta(hours=1), "i", 1000, 1000,
                                    features={"baseline_w": 1000, "sun_elevation_deg": 45}))
        cursor += timedelta(hours=1)
    return instance, tuple(points), start, next_day


async def blocked_executor_update(instance, result, clock, finished_at, *, during_wait=None):
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    resumed = threading.Event()
    executor_threads = []

    def calculate(*args, **kwargs):
        executor_threads.append(threading.get_ident())
        loop.call_soon_threadsafe(started.set)
        assert resumed.wait(15), "test did not release the actual executor"
        return result

    instance.engine.forecast = calculate
    update = asyncio.create_task(instance._async_update_data())
    try:
        await asyncio.wait_for(started.wait(), 15)
        clock.move_to(finished_at)
        if during_wait is not None:
            await during_wait()
    finally:
        resumed.set()
    returned = await update
    assert executor_threads and executor_threads[0] != threading.get_ident()
    return returned


@pytest.mark.parametrize("day,expected_hours", [("2026-03-29", 23), ("2026-06-02", 24), ("2026-10-25", 25)])
@pytest.mark.parametrize("cross_midnight", [False, True])
async def test_async_executor_completion_controls_snapshot_and_training_availability(hass, day, expected_hours, cross_midnight):
    instance, points, start, next_day = instance_and_points(hass, day)
    issue = start - timedelta(minutes=1)
    finished = start + timedelta(minutes=1) if cross_midnight else start - timedelta(seconds=30)
    result = ForecastResult(issue, points)
    with freeze_time(issue, real_asyncio=True) as clock:
        await instance.async_restore()
        assert not instance.daily_snapshots
        assert await blocked_executor_update(instance, result, clock, finished) is result
        if cross_midnight:
            assert day not in instance.daily_snapshots
            assert not any(row["start"] == start.isoformat() for row in instance.archive)
        else:
            assert instance.daily_snapshots[day]["energies"]["i"] == expected_hours
            assert any(row["start"] == start.isoformat() for row in instance.archive)
        # A cutoff miss discards no still-prospective cells or later-day snapshot.
        assert any(row["start"] == (start + timedelta(hours=1)).isoformat() for row in instance.archive)
        later_day = next_day.astimezone(ZoneInfo(instance.site.timezone)).date().isoformat()
        assert later_day in instance.daily_snapshots
        assert all(row["issued_at"] == issue.isoformat() for row in instance.archive)
        await instance.async_close()


@pytest.mark.parametrize("existing_source", ["earlier_forecast", "operator_import"])
async def test_delayed_executor_keeps_existing_forecast_or_operator_import(hass, existing_source):
    day = "2026-06-02"
    instance, points, start, _ = instance_and_points(hass, day)
    issue = start - timedelta(minutes=1)
    result = ForecastResult(issue, points)
    expected = None
    with freeze_time(issue, real_asyncio=True) as clock:
        await instance.async_restore()
        if existing_source == "earlier_forecast":
            earlier = ForecastResult(issue - timedelta(minutes=1), points)
            instance._archive_result(earlier)
            expected = deepcopy((instance.daily_snapshots[day], instance.daily_snapshot_provenance[day]))

        async def import_after_midnight():
            nonlocal expected
            if existing_source == "operator_import":
                instance.async_commit_setup()
                imported = {"issued_at": (issue - timedelta(minutes=5)).isoformat(), "energies": {"i": 12.0}}
                await instance.async_restore_day_start(day, imported, instance.site)
                expected = deepcopy((instance.daily_snapshots[day], instance.daily_snapshot_provenance[day]))
                assert expected[1]["source"] == "operator_restore"

        await blocked_executor_update(instance, result, clock, start + timedelta(minutes=1),
                                      during_wait=import_after_midnight)
        assert (instance.daily_snapshots[day], instance.daily_snapshot_provenance[day]) == expected
        await instance.async_close()


async def test_async_executor_crossing_normal_target_start_cannot_archive_that_training_cell(hass):
    instance, points, midnight, _ = instance_and_points(hass, "2026-06-02")
    target = midnight + timedelta(hours=12)
    issue = target - timedelta(minutes=1)
    result = ForecastResult(issue, tuple(point for point in points if point.start >= target))
    with freeze_time(issue, real_asyncio=True) as clock:
        await instance.async_restore()
        await blocked_executor_update(instance, result, clock, target + timedelta(minutes=1))
        assert not any(row["start"] == target.isoformat() for row in instance.archive)
        assert any(row["start"] == (target + timedelta(hours=1)).isoformat() for row in instance.archive)
        await instance.async_close()


async def test_direct_archive_default_uses_actual_now_without_an_issue_time_fallback(hass):
    instance, points, midnight, next_day = instance_and_points(hass, "2026-06-02")
    result = ForecastResult(midnight - timedelta(minutes=1), points)
    with freeze_time(midnight + timedelta(minutes=1), real_asyncio=True):
        instance._archive_result(result)
        assert "2026-06-02" not in instance.daily_snapshots
        assert not any(row["start"] == midnight.isoformat() for row in instance.archive)
        assert next_day.astimezone(ZoneInfo(instance.site.timezone)).date().isoformat() in instance.daily_snapshots
        await instance.async_close()
