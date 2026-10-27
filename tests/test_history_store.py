"""Read-only history loading preserves real damaged files and migration gates."""
from datetime import timedelta
import errno
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

from freezegun import freeze_time
import pytest

from custom_components.adaptive_solar import coordinator as coordinator_module
from custom_components.adaptive_solar.core.models import WeatherForecast, WeatherPoint
from tests.storage_helpers import seed_store
from tests.test_learning_persistence import NOW, coordinator, evidence


def envelope(store, payload):
    return {"version": store.version, "minor_version": store.minor_version, "key": store.key, "data": payload}


@pytest.mark.parametrize("bad", ["json", "unicode", "empty", "list", "version", "bool_version", "minor",
                                  "bool_minor", "key", "data_none", "missing_data", "empty_data"])
async def test_existing_invalid_primary_never_loads_valid_legacy_or_rewrites_files(hass, bad):
    instance, _ = coordinator(hass)
    seed_store(instance._legacy_store, evidence(instance))
    legacy_path = Path(instance._legacy_store.path)
    legacy_original = legacy_path.read_bytes()
    path = Path(instance._store.path)
    data = envelope(instance._store, {**instance._stored(), **evidence(instance)})
    if bad == "json":
        original = b"{broken"
    elif bad == "unicode":
        original = b'\xff'
    else:
        if bad == "empty":
            data = {}
        elif bad == "list":
            data = []
        elif bad == "version":
            data["version"] = 99
        elif bad == "bool_version":
            data["version"] = True
        elif bad == "minor":
            data["minor_version"] = 99
        elif bad == "bool_minor":
            data["minor_version"] = True
        elif bad == "key":
            data["key"] = "foreign"
        elif bad == "data_none":
            data["data"] = None
        elif bad == "missing_data":
            data.pop("data")
        else:
            data["data"] = {}
        original = json.dumps(data).encode()
    path.write_bytes(original)
    instance._store.async_load = AsyncMock(side_effect=AssertionError("native mutating load forbidden"))
    instance._legacy_store.async_load = AsyncMock(side_effect=AssertionError("legacy fallback forbidden"))
    instance._store.async_save = AsyncMock()
    with freeze_time(NOW + timedelta(hours=2)):
        await instance.async_restore()
        assert instance.archive == instance.intervals == [] and instance.daily_snapshots == {}
        assert not instance._store_writable
        assert instance._history_storage_status == "invalid_primary_preserved_read_only"
        # The protected history does not prevent a valid current physics run.
        now = NOW + timedelta(hours=2)
        instance.client.async_forecasts.return_value = (WeatherForecast("best_match", now, (
            WeatherPoint(now, now + timedelta(hours=1), 500, 600, 100, 20, 2, 30),)),)
        assert (await instance._async_update_data()).points
        instance.async_commit_setup()
        assert not instance._persistence_active and not instance._save_pending
        await instance.async_close()
    instance._store.async_load.assert_not_awaited()
    instance._legacy_store.async_load.assert_not_awaited()
    instance._store.async_save.assert_not_awaited()
    assert path.read_bytes() == original and legacy_path.read_bytes() == legacy_original
    assert not list(path.parent.glob(path.name + ".corrupt.*"))


@pytest.mark.parametrize("bad", ["directory", "permission", "io_error", "disappeared_during_read"])
async def test_existing_unreadable_primary_is_not_missing(hass, monkeypatch, bad):
    instance, _ = coordinator(hass)
    seed_store(instance._legacy_store, evidence(instance))
    path = Path(instance._store.path)
    original = b'{"existing":true}'
    if bad == "directory":
        path.mkdir()
        (path / "marker").write_bytes(original)
    else:
        path.write_bytes(original)
    if bad == "permission":
        path.chmod(0)
    elif bad in ("io_error", "disappeared_during_read"):
        failure = OSError(errno.EIO, "read failed") if bad == "io_error" else FileNotFoundError("after stat")
        monkeypatch.setattr(coordinator_module, "load_json", Mock(side_effect=failure))
    instance._store.async_save = AsyncMock()
    try:
        with freeze_time(NOW + timedelta(hours=2)):
            await instance.async_restore()
            assert not instance._store_writable and instance.intervals == []
            instance.async_commit_setup()
            await instance.async_close()
        instance._store.async_save.assert_not_awaited()
    finally:
        if bad == "permission":
            path.chmod(0o600)
    assert ((path / "marker").read_bytes() if bad == "directory" else path.read_bytes()) == original


@pytest.mark.parametrize("missing_minor", [False, True])
async def test_missing_primary_migrates_only_valid_legacy_after_setup(hass, missing_minor):
    instance, entry = coordinator(hass)
    payload = evidence(instance)
    data = envelope(instance._legacy_store, payload)
    if missing_minor:
        data.pop("minor_version")  # Historical HA Store spelling defaults to minor1.
    legacy_path = Path(instance._legacy_store.path)
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    original = json.dumps(data).encode()
    legacy_path.write_bytes(original)
    primary = Path(instance._store.path)
    with freeze_time(NOW + timedelta(hours=2)):
        await instance.async_restore()
        assert instance._store_writable and instance.intervals == payload["intervals"]
        assert not primary.exists()
        instance.async_commit_setup()
        await instance.async_close()
        assert primary.exists() and json.loads(primary.read_bytes())["data"]["history_schema"] == 2
        reloaded, _ = coordinator(hass, entry)
        await reloaded.async_restore()
        assert reloaded.intervals == payload["intervals"]
        await reloaded.async_close()
    assert legacy_path.read_bytes() == original


async def test_valid_primary_without_minor_is_read_without_migration_or_setup_write(hass):
    instance, _ = coordinator(hass)
    payload = {**instance._stored(), **evidence(instance)}
    data = envelope(instance._store, payload)
    data.pop("minor_version")
    path = Path(instance._store.path)
    path.parent.mkdir(parents=True, exist_ok=True)
    original = json.dumps(data).encode()
    path.write_bytes(original)
    with freeze_time(NOW + timedelta(hours=2)):
        await instance.async_restore()
        assert instance.intervals == payload["intervals"] and instance._store_writable
        assert instance._history_storage_status == "recognized_primary"
        await instance.async_close()  # Failed setup does not rewrite the older readable envelope.
    assert path.read_bytes() == original


@pytest.mark.parametrize("bad", ["json", "envelope"])
async def test_missing_primary_with_unreadable_legacy_starts_neutral_preserving_source(hass, bad):
    instance, _ = coordinator(hass)
    path = Path(instance._legacy_store.path)
    path.parent.mkdir(parents=True, exist_ok=True)
    original = b"{broken" if bad == "json" else b'{}'
    path.write_bytes(original)
    with freeze_time(NOW + timedelta(hours=2)):
        await instance.async_restore()
        assert instance._store_writable and instance.archive == instance.intervals == []
        assert instance._history_storage_status == "invalid_legacy_preserved_new_primary"
        instance.async_commit_setup()
        await instance.async_close()
    assert Path(instance._store.path).exists()
    assert path.read_bytes() == original and not list(path.parent.glob(path.name + ".corrupt.*"))


async def test_delayed_primary_save_materializes_callback_once_and_writes_real_file(hass, monkeypatch):
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    instance, _ = coordinator(hass)
    with freeze_time(NOW) as clock:
        await instance.async_restore()
        original = instance._stored
        callback = Mock(wraps=original)
        monkeypatch.setattr(instance, "_stored", callback)
        instance.async_commit_setup()
        assert not Path(instance._store.path).exists()
        clock.tick(timedelta(seconds=31))
        async_fire_time_changed(hass, NOW + timedelta(seconds=31))
        await hass.async_block_till_done()
        assert callback.call_count == 1
        payload = json.loads(Path(instance._store.path).read_bytes())
        assert payload["data"]["history_schema"] == 2
        await instance.async_close()


async def test_invalid_snapshot_on_physical_change_sets_read_only_storage_diagnosis(hass):
    from dataclasses import replace

    original, entry = coordinator(hass)
    payload = {**original._stored(), **evidence(original),
               "daily_snapshot_provenance": {"2026-06-01": False}}
    changed_config = replace(original.site, strings=(replace(original.site.strings[0], loss_fraction=0.2),))
    changed, _ = coordinator(hass, entry, changed_config)
    seed_store(changed._store, payload)
    with freeze_time(NOW + timedelta(hours=2)):
        await changed.async_restore()
        assert not changed._store_writable
        assert changed._history_storage_status == "invalid_primary_preserved_read_only"
        changed.async_commit_setup()
        assert not changed._persistence_active
        await changed.async_close()
    await original.async_close()
