"""Primary history serialization uses native HA storage outside its event loop."""
import asyncio
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import threading

from freezegun import freeze_time
from homeassistant.helpers import storage
import pytest

from tests.conftest import NATIVE_STORE_WRITE
from tests.test_learning_persistence import NOW, coordinator, evidence

NATIVE_STORE_LOAD = storage.Store._async_load_data


async def test_native_pending_primary_readback_captures_directly_on_loop(hass, monkeypatch):
    instance, _ = coordinator(hass)
    monkeypatch.setattr(instance._store, "_async_write_data", NATIVE_STORE_WRITE.__get__(instance._store))
    with freeze_time(NOW + timedelta(hours=2)):
        await instance.async_restore()
        instance.archive = evidence(instance)["archive"]
        instance.async_commit_setup()
        # Actual native pending-cache path invokes data_func from the HA loop;
        # a worker-only callback bridge would try to wait on this same loop.
        saved = await NATIVE_STORE_LOAD(instance._store)
        assert saved["archive"] == instance.archive
        assert not instance._save_pending
        await instance._store._async_callback_delayed_write()
        assert json.loads(Path(instance._store.path).read_text())["data"] == saved
        await instance.async_close()


@pytest.mark.parametrize("save_path", ["delayed", "operator_import", "close"])
async def test_native_primary_json_is_serialized_in_worker_with_loop_owned_snapshot(hass, monkeypatch, save_path):
    instance, _ = coordinator(hass)
    # Bypass the shared fixture shim: native HA itself must invoke any delayed
    # data_func and select the JSON serialization thread, without a pre-copy.
    monkeypatch.setattr(instance._store, "_async_write_data", NATIVE_STORE_WRITE.__get__(instance._store))
    loop_thread = threading.get_ident()
    snapshot_threads, json_threads = [], []
    stored = instance._stored

    def capture():
        snapshot_threads.append(threading.get_ident())
        return stored()

    monkeypatch.setattr(instance, "_stored", capture)
    prepare = storage.json_helper.prepare_save_json

    def serialize(data, **kwargs):
        if data.get("key") == instance._store.key:
            json_threads.append(threading.get_ident())
        return prepare(data, **kwargs)

    monkeypatch.setattr(storage.json_helper, "prepare_save_json", serialize)
    with freeze_time(NOW + timedelta(hours=2)):
        await instance.async_restore()
        payload = evidence(instance)
        instance.archive, instance.intervals = payload["archive"], payload["intervals"]
        instance.async_commit_setup()
        if save_path == "delayed":
            await instance._store._async_callback_delayed_write()
        elif save_path == "operator_import":
            day, snapshot = next(iter(payload["daily_snapshots"].items()))
            await instance.async_restore_day_start(day, snapshot, instance.site)
        else:
            await instance.async_close()
        saved = json.loads(Path(instance._store.path).read_text())["data"]
        assert saved["archive"] == instance.archive
        assert saved["intervals"] == instance.intervals
        if save_path == "operator_import":
            assert saved["daily_snapshots"][day] == snapshot
        if save_path != "close":
            await instance.async_close()
    assert snapshot_threads and set(snapshot_threads) == {loop_thread}
    assert json_threads and loop_thread not in json_threads


async def test_native_delayed_primary_snapshot_survives_concurrent_meter_merge(hass, monkeypatch):
    instance, _ = coordinator(hass)
    monkeypatch.setattr(instance._store, "_async_write_data", NATIVE_STORE_WRITE.__get__(instance._store))
    loop_thread = threading.get_ident()
    entered, release = asyncio.Event(), threading.Event()
    prepare = storage.json_helper.prepare_save_json

    def serialize(data, **kwargs):
        if data.get("key") == instance._store.key:
            # Fail deterministically on the old implementation; never block
            # the loop waiting for itself to deliver the concurrent report.
            assert threading.get_ident() != loop_thread
            hass.loop.call_soon_threadsafe(entered.set)
            assert release.wait(10), "test did not release the serializer"
        return prepare(data, **kwargs)

    monkeypatch.setattr(storage.json_helper, "prepare_save_json", serialize)
    with freeze_time(NOW + timedelta(hours=2)):
        await instance.async_restore()
        instance.archive = evidence(instance)["archive"]
        first = {"inverter_id": "i", "start": NOW.isoformat(),
                 "end": (NOW + timedelta(minutes=5)).isoformat(),
                 "observed_at": (NOW + timedelta(minutes=5)).isoformat(), "energy_kwh": 0.1,
                 "measurement_contract": "counter-lineage-support-v2", "continuity_id": "native-save-test"}
        instance._append_interval(first)
        before = deepcopy(instance.intervals)
        instance.async_commit_setup()
        writing = hass.async_create_task(instance._store._async_callback_delayed_write())
        waiting = asyncio.create_task(entered.wait())
        try:
            completed, _ = await asyncio.wait((writing, waiting), return_when=asyncio.FIRST_COMPLETED)
            if writing in completed:
                await writing
            assert entered.is_set()
            second = {**first, "start": first["end"],
                      "end": (NOW + timedelta(minutes=10)).isoformat(),
                      "observed_at": (NOW + timedelta(minutes=10)).isoformat()}
            instance._append_interval(second)
            instance._schedule_save()
            assert instance._save_pending
            assert instance.intervals[0]["energy_kwh"] == pytest.approx(0.2)
        finally:
            release.set()
            waiting.cancel()
            await writing
        saved = json.loads(Path(instance._store.path).read_text())["data"]
        assert saved["intervals"] == before
        assert instance._save_pending  # A concurrent new report retains its own delayed save.
        await instance._store._async_callback_delayed_write()
        saved = json.loads(Path(instance._store.path).read_text())["data"]
        assert saved["intervals"][0]["energy_kwh"] == pytest.approx(0.2)
        assert len(saved["intervals"][0]["measurement_parts"]) == 2
        assert not instance._save_pending
        await instance.async_close()
