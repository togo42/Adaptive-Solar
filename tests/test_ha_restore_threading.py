"""Native HA remains responsive while private restore candidates are checked."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
import threading

from freezegun import freeze_time
import pytest

from custom_components.adaptive_solar import coordinator as module
from custom_components.adaptive_solar.core.comparison_archive import ComparisonArchive
from custom_components.adaptive_solar.core.models import ForecastPoint
from custom_components.adaptive_solar.snapshots import provenance
from tests.storage_helpers import seed_store
from tests.test_learning_persistence import NOW, coordinator, evidence


def large_history(instance):
    payload = {**instance._stored(), **evidence(instance), "archive": [], "intervals": []}
    for hour in range(2400):
        start = NOW - timedelta(hours=2399 - hour)
        end = start + timedelta(hours=1)
        payload["archive"].append({"issued_at": (start - timedelta(hours=1)).isoformat(),
            "start": start.isoformat(), "end": end.isoformat(), "inverter_id": "i", "baseline_w": 2000,
            "features": {"baseline_w": 2000, "sun_elevation_deg": 45, "lead_hours": 1.5}})
        parts = [[(start + timedelta(minutes=minute)).isoformat(),
                  (start + timedelta(minutes=minute + 15)).isoformat(), end.isoformat(), 0.25]
                 for minute in range(0, 60, 15)]
        payload["intervals"].append({"start": start.isoformat(), "end": end.isoformat(),
            "observed_at": end.isoformat(), "energy_kwh": 1.0, "inverter_id": "i",
            "measurement_contract": module.MEASUREMENT_CONTRACT, "continuity_id": "a" * 32,
            "measurement_parts": parts})
    return payload


def guard_loop_owned_state(instance, loop_thread):
    class LoopOwnedCoordinator(type(instance)):
        def __setattr__(self, name, value):
            if name in {"archive", "intervals", "daily_snapshots", "daily_snapshot_provenance", "shading",
                        "_interval_latest", "_measurement_part_count", "_store_writable", "_history_storage_status",
                        "_comparison_archive"}:
                assert threading.get_ident() == loop_thread, f"worker mutated coordinator.{name}"
            super().__setattr__(name, value)

    instance.__class__ = LoopOwnedCoordinator


@pytest.mark.parametrize("legacy", [False, True])
async def test_native_large_restore_checks_in_worker_and_keeps_loop_responsive(hass, monkeypatch, legacy):
    instance, _ = coordinator(hass)
    loop_thread = threading.get_ident()
    guard_loop_owned_state(instance, loop_thread)
    with freeze_time(NOW + timedelta(hours=2), real_asyncio=True):
        payload = large_history(instance)
        store = instance._legacy_store if legacy else instance._store
        seed_store(store, payload)
        path = Path(store.path)
        original = path.read_bytes()
        calls = {}
        entered, release = asyncio.Event(), threading.Event()
        for name in ("load_json", "ForecastPoint", "expand_interval", "join_training", "validate_snapshot"):
            original_call = getattr(module, name)

            def check(*args, _name=name, _call=original_call, **kwargs):
                calls[_name] = calls.get(_name, 0) + 1
                assert threading.get_ident() != loop_thread, f"{_name} ran on HA loop"
                if _name == "join_training":
                    hass.loop.call_soon_threadsafe(entered.set)
                    assert release.wait(10), "test did not release restore worker"
                return _call(*args, **kwargs)

            monkeypatch.setattr(module, name, check)
        restoring = hass.async_create_task(instance.async_restore())
        waiting = asyncio.create_task(entered.wait())
        try:
            done, _ = await asyncio.wait((restoring, waiting), return_when=asyncio.FIRST_COMPLETED)
            if restoring in done:
                await restoring
            assert entered.is_set()
            # An actual HA event is delivered while the worker holds its
            # validation barrier. This does not rely on a latency threshold.
            delivered = asyncio.Event()
            hass.bus.async_listen_once("adaptive_solar_restore_probe", lambda _: delivered.set())
            hass.bus.async_fire("adaptive_solar_restore_probe")
            await delivered.wait()
            assert not restoring.done()
            assert instance.archive == instance.intervals == []
            assert instance.daily_snapshots == {}
            assert not instance._persistence_active
        finally:
            release.set()
            waiting.cancel()
            await restoring
        assert set(calls) == {"load_json", "ForecastPoint", "expand_interval", "join_training", "validate_snapshot"}
        assert instance.archive == payload["archive"]
        assert instance.intervals == payload["intervals"]
        assert instance.daily_snapshots == payload["daily_snapshots"]
        assert instance._measurement_part_count == 9600
        assert len(instance._interval_latest) == 2400
        assert instance.tracker.anchors == {}
        assert instance._store_writable and not instance._persistence_active
        await instance.async_close()  # Uncommitted setup must preserve both namespaces.
        assert path.read_bytes() == original
        if legacy:
            assert not Path(instance._store.path).exists()


@pytest.mark.parametrize("invalid", [False, True])
async def test_native_changed_physics_snapshot_validation_runs_in_worker(hass, monkeypatch, invalid):
    old, entry = coordinator(hass)
    payload = {**old._stored(), **evidence(old)}
    payload["daily_snapshot_provenance"] = {"2026-06-01": provenance(old.site)}
    if invalid:
        payload["daily_snapshots"]["2026-06-01"]["energies"]["i"] = True
    changed, _ = coordinator(hass, entry, replace(old.site, strings=(replace(old.site.strings[0], loss_fraction=0.2),)))
    with freeze_time(NOW + timedelta(hours=2), real_asyncio=True):
        seed_store(changed._store, payload)
        path = Path(changed._store.path)
        original = path.read_bytes()
        validate = module.validate_snapshot
        threads = []

        def checked(*args, **kwargs):
            threads.append(threading.get_ident())
            assert threading.get_ident() != hass.loop_thread_id
            return validate(*args, **kwargs)

        monkeypatch.setattr(module, "validate_snapshot", checked)
        guard_loop_owned_state(changed, hass.loop_thread_id)
        await changed.async_restore()
        assert threads
        assert changed.archive == changed.intervals == []
        assert changed._store_writable is not invalid
        assert bool(changed.daily_snapshots) is not invalid
        assert not changed._persistence_active
        await changed.async_close()
        assert path.read_bytes() == original
    await old.async_close()


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("bad", ["interval", "parts", "snapshot"])
async def test_native_invalid_history_is_validated_off_loop_and_preserved(hass, monkeypatch, legacy, bad):
    instance, _ = coordinator(hass)
    with freeze_time(NOW + timedelta(hours=2), real_asyncio=True):
        payload = {**instance._stored(), **deepcopy(evidence(instance))}
        if bad == "interval":
            payload["intervals"][0]["energy_kwh"] = True
        elif bad == "parts":
            payload["intervals"][0]["measurement_parts"] = []
        else:
            payload["daily_snapshots"]["2026-06-01"]["energies"]["i"] = True
        store = instance._legacy_store if legacy else instance._store
        seed_store(store, payload)
        path = Path(store.path)
        original = path.read_bytes()
        point = module.ForecastPoint
        threads = []

        def checked(*args, **kwargs):
            threads.append(threading.get_ident())
            assert threading.get_ident() != hass.loop_thread_id
            return point(*args, **kwargs)

        monkeypatch.setattr(module, "ForecastPoint", checked)
        guard_loop_owned_state(instance, hass.loop_thread_id)
        await instance.async_restore()
        if bad != "parts":
            assert threads
        assert instance.archive == instance.intervals == []
        assert instance._store_writable is legacy
        assert instance._history_storage_status == ("invalid_legacy_preserved_new_primary" if legacy
                                                   else "invalid_primary_preserved_read_only")
        await instance.async_close()
        assert path.read_bytes() == original


async def test_native_comparison_restore_validates_and_prunes_private_candidate_in_worker(hass, monkeypatch):
    instance, _ = coordinator(hass)
    at = NOW + timedelta(hours=8)
    archive = ComparisonArchive(instance._fingerprint, instance._history_fingerprint, {"i": 5000}, instance.site.timezone)
    archive.capture({"adaptive": (ForecastPoint(at + timedelta(hours=1), at + timedelta(hours=2), "i", 1000, 1000),)},
                    calculated_at=at, received_at=at, weather_issues={})
    assert archive.snapshots
    seed_store(instance._comparison_store, archive.to_dict())
    path = Path(instance._comparison_store.path)
    original = path.read_bytes()
    load, prune = ComparisonArchive.from_dict, ComparisonArchive.prune
    threads = []

    def checked_load(cls, value, **kwargs):
        assert threading.get_ident() != hass.loop_thread_id
        threads.append("validate")
        return load(value, **kwargs)

    def checked_prune(candidate, now):
        assert threading.get_ident() != hass.loop_thread_id
        threads.append("prune")
        return prune(candidate, now)

    monkeypatch.setattr(ComparisonArchive, "from_dict", classmethod(checked_load))
    monkeypatch.setattr(ComparisonArchive, "prune", checked_prune)
    guard_loop_owned_state(instance, hass.loop_thread_id)
    with freeze_time(at, real_asyncio=True):
        await instance.async_restore()
        assert threads == ["validate", "prune"]
        assert instance._comparison_archive.to_dict() == archive.to_dict()
        assert instance._comparison_store_writable and not instance._comparison_persistence_active
        await instance.async_close()
    assert path.read_bytes() == original
