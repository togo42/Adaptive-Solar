"""Nighttime numerical undershoot and immutable historical forecast recovery."""
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from freezegun import freeze_time
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import Context
from homeassistant.exceptions import Unauthorized
from homeassistant.helpers.storage import Store
from pytest_homeassistant_custom_component.common import MockConfigEntry
import pytest

from custom_components.adaptive_solar import services
from custom_components.adaptive_solar.coordinator import AdaptiveSolarCoordinator
from custom_components.adaptive_solar.core.engine import ForecastEngine
from custom_components.adaptive_solar.core.models import InverterConfig, SiteConfig, StringConfig
from custom_components.adaptive_solar.sensor import AdaptiveSolarSensor, day_bounds
from custom_components.adaptive_solar.snapshots import provenance
from custom_components.adaptive_solar.weather import UNITS, VARIABLES, WeatherError, parse_forecast

NOW = datetime(2026, 10, 27, 12, tzinfo=UTC)
DAY = "2026-10-27"
SNAPSHOT = {"issued_at": "2026-10-26T22:55:00+00:00", "energies": {"i": 20.0}}
NATIVE_WRITE = Store._async_write_data  # Before HA fixtures patch storage to RAM.


def site():
    return SiteConfig(52, 13, "Europe/Berlin", (StringConfig("s", "i", 5, 30, 180),), (InverterConfig("i", 5),))


def weather(end, values=(-1, 0, 0)):
    result = {"hourly_units": dict(UNITS), "hourly": {
        "time": [(end - timedelta(hours=1)).timestamp(), end.timestamp(), (end + timedelta(hours=1)).timestamp()],
        **{key: [value] * 3 for key, value in zip(VARIABLES, [0, 0, 0, 10, 2, 30], strict=True)}}}
    for key, value in zip(VARIABLES[:3], values, strict=True):
        result["hourly"][key][1] = value
    return result


@pytest.mark.parametrize("values", [(-1, 0, 0), (0, -0.5, 0), (0, 0, -1), (-1, -1, -1)])
@pytest.mark.parametrize("end", [datetime(2026, 10, 30, 20, tzinfo=UTC),
                                 datetime(2026, 3, 29, 1, tzinfo=UTC), datetime(2026, 10, 25, 1, tzinfo=UTC)])
def test_small_undershoot_at_night_is_normalized_with_raw_diagnostics_without_mutating_input(end, values):
    raw = weather(end, values)
    saved = deepcopy(raw)
    diagnostics = {}
    result = parse_forecast(raw, "best_match", NOW, site(), diagnostics)
    point = result.points[0]
    assert len(result.points) == 2 and (point.start, point.end) == (end - timedelta(hours=1), end)
    assert (point.ghi_w_m2, point.dni_w_m2, point.dhi_w_m2) == (0, 0, 0)
    assert diagnostics["normalized_count"] == 1 and diagnostics["rejected_radiation_count"] == 0
    assert list(diagnostics["normalized_examples"][0]["raw_w_m2"].values()) == list(values)
    assert raw == saved


@pytest.mark.parametrize("values", [(None, 0, 0), (True, 0, 0), (float("nan"), 0, 0),
                                   (float("inf"), 0, 0), (-1.001, 0, 0), (-1, 0.01, 0)])
def test_nighttime_missing_or_grossly_invalid_values_stay_gaps(values):
    diagnostics = {}
    end = datetime(2026, 10, 30, 20, tzinfo=UTC)
    result = parse_forecast(weather(end, values), "best_match", NOW, site(), diagnostics)
    assert len(result.points) == 1 and result.points[0].start == end
    assert diagnostics["normalized_count"] == 0 and diagnostics["rejected_radiation_count"] == 1


@pytest.mark.parametrize("hour", [7, 12, 16])
def test_twilight_and_daylight_undershoot_is_not_normalized(hour):
    end = datetime(2026, 10, 30, hour, tzinfo=UTC)
    result = parse_forecast(weather(end), "best_match", NOW, site())
    assert len(result.points) == 1 and result.points[0].start == end


@pytest.mark.parametrize("month,accepted", [(6, False), (12, True)])
def test_polar_day_and_night_use_location_geometry(month, accepted):
    end = datetime(2026, month, 20, 23, tzinfo=UTC)
    result = parse_forecast(weather(end), "best_match", NOW, replace(site(), latitude=80))
    assert len(result.points) == (2 if accepted else 1)


def test_unknown_location_and_invalid_ambient_never_gain_coverage():
    end = datetime(2026, 10, 30, 20, tzinfo=UTC)
    assert len(parse_forecast(weather(end), "best_match", NOW).points) == 1
    raw = weather(end)
    raw["hourly"]["temperature_2m"][1] = None
    with pytest.raises(WeatherError, match="no usable"):
        parse_forecast(raw, "best_match", NOW, site())


def test_normalized_night_interval_restores_real_full_day_energy_coverage():
    config = site()
    start, end = day_bounds(NOW, config.timezone, 3)
    raw = weather(start)
    raw["hourly"]["time"] = [(start + timedelta(hours=i)).timestamp() for i in range(25)]
    for key, value in zip(VARIABLES, [0, 0, 0, 10, 2, 30], strict=True):
        raw["hourly"][key] = [value] * 25
    raw["hourly"]["shortwave_radiation"][21] = -1
    before = parse_forecast(raw, "best_match", NOW)
    after = parse_forecast(raw, "best_match", NOW, config)
    engine = ForecastEngine(config)
    assert engine.forecast((before,), NOW).energy_kwh(start, end, "i") is None
    assert engine.forecast((after,), NOW).energy_kwh(start, end, "i") == 0


def coordinator(hass, config=None, entry=None):
    config = config or site()
    if entry is None:
        entry = MockConfigEntry(domain="adaptive_solar", data={"site": config.to_dict()})
        entry.add_to_hass(hass)
    return AdaptiveSolarCoordinator(hass, entry, config, AsyncMock()), entry


def enable_snapshot_disk_writes(instance):
    """Exercise HA's real writer as well as its fixture's reload memory map."""
    memory_write = instance._store._async_write_data

    async def write(data):
        await NATIVE_WRITE(instance._store, deepcopy(data))
        await memory_write(data)

    instance._store._async_write_data = write


@pytest.mark.parametrize("change", ["damping", "horizon", "energy", "cap"])
@freeze_time(NOW)
async def test_physical_change_retains_only_issued_historical_forecasts_with_original_provenance(hass, change):
    first, entry = coordinator(hass)
    await first.async_restore()
    first.daily_snapshots = {DAY: deepcopy(SNAPSHOT), "2026-10-28": deepcopy(SNAPSHOT)}
    first.async_commit_setup()
    await first.async_close()
    options = {}
    if change in {"damping", "horizon"}:
        from custom_components.adaptive_solar.core.models import HorizonPoint
        options["strings"] = (replace(site().strings[0], **({"damping_morning": 0.2} if change == "damping"
                                                          else {"horizon": (HorizonPoint(180, 20),)})),)
    else:
        options["inverters"] = (replace(site().inverters[0], **({"energy_entity_id": "sensor.new_energy"} if change == "energy"
                                                               else {"max_ac_kw": 0.5, "max_output_kw": 0.5})),)
    changed, _ = coordinator(hass, replace(site(), **options), entry)
    await changed.async_restore()
    assert changed.daily_snapshots == {DAY: SNAPSHOT}
    assert changed.daily_snapshot_provenance[DAY] == provenance(site())
    assert changed.archive == changed.intervals == [] and not changed.tracker.anchors
    changed.async_commit_setup()
    await changed.async_close()
    restored, _ = coordinator(hass, changed.site, entry)
    await restored.async_restore()
    assert restored.daily_snapshots == {DAY: SNAPSHOT}
    assert restored.daily_snapshot_provenance[DAY] == provenance(site())
    sensor = AdaptiveSolarSensor(restored, entry, "i", "day", 0)
    restored.data = ForecastEngine(restored.site).forecast((parse_forecast(weather(NOW + timedelta(hours=1), (0, 0, 0)), "x", NOW),), NOW)
    assert sensor.native_value == 20
    assert sensor.extra_state_attributes["forecast_configuration_changed"] is True
    assert sensor.extra_state_attributes["forecast_provenance"]["config_fingerprint"] == first._fingerprint
    await restored.async_close()


@freeze_time(NOW)
async def test_opaque_old_snapshot_cannot_cross_history_change(hass):
    first, entry = coordinator(hass)
    payload = first._stored()
    payload["daily_snapshots"] = {DAY: SNAPSHOT}
    await first._store.async_save(payload)
    changed, _ = coordinator(hass, replace(site(), strings=(replace(site().strings[0], damping_morning=0.2),)), entry)
    await changed.async_restore()
    assert not changed.daily_snapshots and changed._store_writable
    await changed.async_close()


@freeze_time(NOW)
async def test_legacy_snapshot_keeps_original_full_hash_after_weather_change(hass):
    first, entry = coordinator(hass)
    stored = first._stored()
    stored["daily_snapshots"] = {DAY: SNAPSHOT}
    await first._store.async_save(stored)
    changed, _ = coordinator(hass, replace(site(), weather_models=("icon_eu",)), entry)
    await changed.async_restore()
    assert changed.daily_snapshots == {DAY: SNAPSHOT}
    assert changed.daily_snapshot_provenance[DAY]["config_fingerprint"] == first._fingerprint
    assert changed.daily_snapshot_provenance[DAY]["config_fingerprint"] != changed._fingerprint
    await changed.async_close()


@freeze_time(NOW)
async def test_import_restores_only_original_forecast_and_roundtrips_without_training_data(hass):
    instance, entry = coordinator(hass)
    enable_snapshot_disk_writes(instance)
    await instance.async_restore()
    instance.async_commit_setup()
    original = replace(site(), strings=(replace(site().strings[0], damping_morning=0.3),))
    await instance.async_restore_day_start(DAY, SNAPSHOT, original)
    assert instance.archive == instance.intervals == [] and not instance.tracker.anchors
    assert instance.daily_snapshot_provenance[DAY] == provenance(original, source="operator_restore")
    with pytest.raises(ValueError, match="missing"):
        await instance.async_restore_day_start(DAY, SNAPSHOT, original)
    await instance.async_close()
    restored, _ = coordinator(hass, entry=entry)
    await restored.async_restore()
    assert restored.daily_snapshots[DAY] == SNAPSHOT
    assert restored.daily_snapshot_provenance[DAY] == instance.daily_snapshot_provenance[DAY]
    await restored.async_close()


@pytest.mark.parametrize("bad", ["late", "negative", "over_cap", "boolean", "foreign_stage", "location", "timezone", "future", "old"])
@freeze_time(NOW)
async def test_import_rejects_invalid_or_incompatible_historical_records(hass, bad):
    instance, _ = coordinator(hass)
    await instance.async_restore()
    instance.async_commit_setup()
    snapshot, source, day = deepcopy(SNAPSHOT), site(), DAY
    if bad == "late":
        snapshot["issued_at"] = NOW.isoformat()
    elif bad in {"negative", "over_cap", "boolean"}:
        snapshot["energies"]["i"] = {"negative": -1, "over_cap": 1000, "boolean": True}[bad]
    elif bad == "foreign_stage":
        snapshot["energies"] = {"other": 1}
    elif bad in {"location", "timezone"}:
        source = replace(source, **({"latitude": 53} if bad == "location" else {"timezone": "UTC"}))
    else:
        day = "2026-10-28" if bad == "future" else "2026-10-01"
    with pytest.raises(ValueError):
        await instance.async_restore_day_start(day, snapshot, source)
    assert not instance.daily_snapshots and not instance.daily_snapshot_provenance
    await instance.async_close()


@freeze_time(NOW)
async def test_failed_import_write_rolls_back_without_publishing(hass):
    instance, _ = coordinator(hass)
    await instance.async_restore()
    instance.async_commit_setup()
    with patch.object(instance._store, "async_save", new=AsyncMock(side_effect=OSError)), patch.object(instance, "async_update_listeners") as notify:
        with pytest.raises(OSError):
            await instance.async_restore_day_start(DAY, SNAPSHOT, site())
        notify.assert_not_called()
    assert not instance.daily_snapshots
    await instance.async_close()


@freeze_time(NOW)
async def test_native_store_logged_disk_error_cannot_publish_import(hass):
    from homeassistant.helpers.storage import WriteError

    instance, _ = coordinator(hass)
    enable_snapshot_disk_writes(instance)
    await instance.async_restore()
    instance.async_commit_setup()
    await instance._store.async_save(instance._stored())
    with patch.object(instance._store, "_async_write_data", new=AsyncMock(side_effect=WriteError("disk full"))), patch.object(instance, "async_update_listeners") as notify:
        with pytest.raises(ValueError, match="readback"):
            await instance.async_restore_day_start(DAY, SNAPSHOT, site())
        notify.assert_not_called()
    assert not instance.daily_snapshots and not instance._pending_day_start_imports
    await instance.async_close()


@freeze_time(NOW)
async def test_pending_import_is_not_sensor_visible_and_duplicate_import_is_blocked(hass):
    instance, _ = coordinator(hass)
    enable_snapshot_disk_writes(instance)
    await instance.async_restore()
    instance.async_commit_setup()
    original_save = instance._store.async_save

    async def save(data):
        assert not instance.daily_snapshots
        assert instance._stored()["daily_snapshots"][DAY] == SNAPSHOT
        with pytest.raises(ValueError, match="missing"):
            await instance.async_restore_day_start(DAY, SNAPSHOT, site())
        await original_save(data)

    with patch.object(instance._store, "async_save", side_effect=save):
        await instance.async_restore_day_start(DAY, SNAPSHOT, site())
    assert instance.daily_snapshots[DAY] == SNAPSHOT and not instance._pending_day_start_imports
    await instance.async_close()


async def test_restore_service_requires_admin_and_registers_and_releases_with_owners(hass, hass_read_only_user):
    services.async_register_reference_service(hass, "owner")
    native = AsyncMock()
    loaded = SimpleNamespace(domain="adaptive_solar", state=ConfigEntryState.LOADED,
                             runtime_data=SimpleNamespace(async_restore_day_start=native))
    data = {"config_entry_id": "owner", "day": DAY, "snapshot": SNAPSHOT, "source_site": site().to_dict()}
    with patch.object(hass.config_entries, "async_get_entry", return_value=loaded):
        with pytest.raises(Unauthorized):
            await hass.services.async_call("adaptive_solar", services.RESTORE_SERVICE, data,
                                           blocking=True, context=Context(user_id=hass_read_only_user.id))
        native.assert_not_called()
        await hass.services.async_call("adaptive_solar", services.RESTORE_SERVICE, data, blocking=True)
        native.assert_awaited_once_with(DAY, SNAPSHOT, site())
    services.async_unregister_reference_service(hass, "owner")
    assert not hass.services.has_service("adaptive_solar", services.RESTORE_SERVICE)
