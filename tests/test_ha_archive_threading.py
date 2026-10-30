"""Representative-origin selection yields to HA without changing archive cutoffs."""
import asyncio
from copy import deepcopy
from datetime import timedelta
import threading
from unittest.mock import Mock

from freezegun import freeze_time
from homeassistant.helpers.update_coordinator import UpdateFailed
import pytest

from custom_components.adaptive_solar import coordinator as module
from custom_components.adaptive_solar.core.models import ForecastPoint, ForecastResult
from tests.test_archive_availability import instance_and_points
from tests.test_ha_restore_threading import large_history
from tests.test_meter_quality import NOW, coordinator


async def selection_barrier(instance, result, monkeypatch, during_wait):
    """Pause the real selector worker; the original code fails before blocking."""
    entered, release = asyncio.Event(), threading.Event()
    paired = module._paired_forecast_origins
    calls = []

    def blocked(*args, **kwargs):
        assert threading.get_ident() != instance.hass.loop_thread_id, "archive selection ran on HA loop"
        calls.append(len(args[0]))
        if len(calls) == 1:
            instance.hass.loop.call_soon_threadsafe(entered.set)
            assert release.wait(15), "test did not release selector worker"
        return paired(*args, **kwargs)

    monkeypatch.setattr(module, "_paired_forecast_origins", blocked)
    instance.engine.forecast = Mock(return_value=result)
    updating = instance.hass.async_create_task(instance._async_update_data())
    waiting = asyncio.create_task(entered.wait())
    try:
        done, _ = await asyncio.wait((updating, waiting), return_when=asyncio.FIRST_COMPLETED)
        if updating in done:
            await updating
        assert entered.is_set()
        await during_wait(updating)
    finally:
        release.set()
        waiting.cancel()
    return await updating, calls


async def test_native_large_archive_selection_keeps_meter_events_and_loop_responsive(hass, monkeypatch):
    instance = coordinator(hass)
    result = ForecastResult(NOW, tuple(ForecastPoint(NOW + timedelta(hours=hour), NOW + timedelta(hours=hour + 1),
        "i", 1000, 1000, features={"baseline_w": 1000, "sun_elevation_deg": 45}) for hour in (2, 3)))
    with freeze_time(NOW, real_asyncio=True) as clock:
        await instance.async_restore()
        instance.archive = large_history(instance)["archive"]
        initial_rows = tuple(instance.archive)
        hass.states.async_set("binary_sensor.curtailed", "off")
        instance.async_start_tracking()
        hass.states.async_set("sensor.energy", "1", {"unit_of_measurement": "kWh"})
        await hass.async_block_till_done()

        async def during(updating):
            clock.tick(timedelta(minutes=1))
            hass.states.async_set("sensor.energy", "1.01", {"unit_of_measurement": "kWh"})
            probe = asyncio.Event()
            hass.bus.async_listen_once("adaptive_solar_archive_probe", lambda _: probe.set())
            hass.bus.async_fire("adaptive_solar_archive_probe")
            await probe.wait()
            assert not updating.done()
            assert tuple(instance.archive) == initial_rows
            assert instance.intervals[0]["energy_kwh"] == pytest.approx(0.01)

        returned, calls = await selection_barrier(instance, result, monkeypatch, during)
        assert returned is result and calls == [2402]
        assert instance.intervals[0]["energy_kwh"] == pytest.approx(0.01)
        assert any(row["start"] == (NOW + timedelta(hours=2)).isoformat() for row in instance.archive)
        assert {id(row) for row in initial_rows}.issubset({id(row) for row in instance.archive})
        await instance.async_close()


@pytest.mark.parametrize("day,hours", [("2026-03-29", 23), ("2026-06-02", 24), ("2026-10-25", 25)])
@pytest.mark.parametrize("cross_start", [False, True])
async def test_selector_worker_return_controls_training_and_day_start_cutoffs(hass, monkeypatch, day, hours, cross_start):
    instance, points, start, next_day = instance_and_points(hass, day)
    issue = start - timedelta(minutes=1)
    result = ForecastResult(issue, points)
    with freeze_time(issue, real_asyncio=True) as clock:
        await instance.async_restore()

        async def during(_updating):
            clock.move_to(start + timedelta(minutes=1) if cross_start else start)

        returned, calls = await selection_barrier(instance, result, monkeypatch, during)
        assert returned is result
        assert len(calls) == (2 if cross_start else 1)
        if cross_start:
            assert day not in instance.daily_snapshots
            assert not any(row["start"] == start.isoformat() for row in instance.archive)
        else:
            assert instance.daily_snapshots[day]["energies"]["i"] == hours
            assert any(row["start"] == start.isoformat() for row in instance.archive)
        assert any(row["start"] == next_day.isoformat() for row in instance.archive)
        assert all(row["issued_at"] == issue.isoformat() for row in instance.archive)
        await instance.async_close()


async def test_selector_retry_preserves_operator_import_during_worker(hass, monkeypatch):
    day = "2026-06-02"
    instance, points, start, _ = instance_and_points(hass, day)
    issue = start - timedelta(minutes=1)
    result = ForecastResult(issue, points)
    imported = {"issued_at": (issue - timedelta(minutes=5)).isoformat(), "energies": {"i": 12.0}}
    with freeze_time(issue, real_asyncio=True) as clock:
        await instance.async_restore()
        instance.async_commit_setup()
        expected = None

        async def during(_updating):
            nonlocal expected
            clock.move_to(start + timedelta(minutes=1))
            await instance.async_restore_day_start(day, imported, instance.site)
            expected = deepcopy((instance.daily_snapshots[day], instance.daily_snapshot_provenance[day]))

        await selection_barrier(instance, result, monkeypatch, during)
        assert (instance.daily_snapshots[day], instance.daily_snapshot_provenance[day]) == expected
        assert instance.daily_snapshot_provenance[day]["source"] == "operator_restore"
        await instance.async_close()


async def test_selector_retries_real_retention_change_without_resurrecting_rows(hass, monkeypatch):
    instance = coordinator(hass)
    result = ForecastResult(NOW, (ForecastPoint(NOW + timedelta(hours=2), NOW + timedelta(hours=3), "i", 1000, 1000,
        features={"baseline_w": 1000, "sun_elevation_deg": 45}),))
    with freeze_time(NOW, real_asyncio=True) as clock:
        await instance.async_restore()
        end = NOW - timedelta(days=module.RETENTION_DAYS) + timedelta(seconds=30)
        expired = {"issued_at": (end - timedelta(hours=2)).isoformat(),
                   "start": (end - timedelta(hours=1)).isoformat(), "end": end.isoformat(),
                   "inverter_id": "i", "baseline_w": 1000,
                   "features": {"baseline_w": 1000, "sun_elevation_deg": 45}}
        instance.archive = [expired]

        async def during(_updating):
            clock.tick(timedelta(minutes=1))
            instance._prune(NOW + timedelta(minutes=1))
            assert instance.archive == []

        _, calls = await selection_barrier(instance, result, monkeypatch, during)
        assert calls == [2, 1]
        assert expired not in instance.archive
        await instance.async_close()


async def test_close_during_selector_worker_does_not_commit_candidate(hass, monkeypatch):
    instance, points, start, _ = instance_and_points(hass, "2026-06-02")
    issue = start - timedelta(minutes=1)
    result = ForecastResult(issue, points)
    with freeze_time(issue, real_asyncio=True):
        await instance.async_restore()

        async def during(_updating):
            await instance.async_close()

        with pytest.raises(UpdateFailed, match="closed"):
            await selection_barrier(instance, result, monkeypatch, during)
        assert instance.archive == [] and instance.daily_snapshots == {}
