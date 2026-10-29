"""Prospective local availability, isolated persistence and evaluation adapter."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import json
from unittest.mock import AsyncMock, Mock

from homeassistant.helpers.storage import Store
from freezegun import freeze_time
import pytest

from tests.storage_helpers import seed_store

from custom_components.adaptive_solar.core import comparison_archive as archive_module
from custom_components.adaptive_solar.core.comparison_archive import COMPARISON_ARCHIVE_KEY, ComparisonArchive
from custom_components.adaptive_solar.core.evaluation import ActualRecord, EvaluationWindow, evaluate_forecasts
from custom_components.adaptive_solar.core.models import ForecastPoint, ForecastResult
from scripts.evaluate import forecast_records_from_comparison_archive
from tests.test_cli import offline_process as offline_process
from tests.test_meter_quality import coordinator
from tests.test_training_alignment import NOW as ORIGINAL_NOW, measured

NATIVE_WRITE = Store._async_write_data
NOW = ORIGINAL_NOW + timedelta(hours=8)


def point(start=NOW + timedelta(hours=1), inverter="i", power=1000):
    return ForecastPoint(start, start + timedelta(hours=1), inverter, 900, power,
                         features={"baseline_w": 900, "sun_elevation_deg": 45})


def archive(caps=None):
    return ComparisonArchive("a" * 64, "b" * 64, caps or {"i": 5000})


def capture(instance, received=NOW, points=None, source="adaptive", weather_issue=NOW - timedelta(hours=1)):
    instance.capture({source: tuple(points) if points is not None else (point(),)}, calculated_at=received,
                     received_at=received, weather_issues={source: {"best_match": weather_issue}})


def test_comparison_retains_first_actual_daily_capture_and_original_weather_issue():
    instance = archive()
    received = NOW + timedelta(seconds=5)
    capture(instance, received)
    original = instance.to_dict()
    for minute in range(1, 60):
        capture(instance, NOW + timedelta(minutes=minute), points=[point(power=2000)])
    assert instance.to_dict() == original
    row = instance.snapshots[0]
    assert row["retrieved_at"] == received.isoformat()
    assert row["weather_issued_at"]["best_match"] == (NOW - timedelta(hours=1)).isoformat()
    capture(instance, NOW + timedelta(days=1))
    assert len(instance.snapshots) == 2
    assert instance.snapshots[-1]["retrieved_at"] == (NOW + timedelta(days=1)).isoformat()


def test_daily_capture_policy_keeps_the_real_first_receipt_after_local_18():
    instance = ComparisonArchive("a" * 64, "b" * 64, {"i": 5000}, "Europe/Berlin")
    before = NOW.replace(hour=15, minute=59)  #17:59 local summer time.
    capture(instance, before)
    assert instance.snapshots == []
    first = NOW.replace(hour=16, minute=7)
    capture(instance, first, weather_issue=first - timedelta(hours=1))
    capture(instance, NOW.replace(hour=17), weather_issue=first - timedelta(hours=1))
    assert len(instance.snapshots) == 1
    assert instance.snapshots[0]["retrieved_at"] == first.isoformat()
    assert instance.snapshots[0]["calculated_at"] == first.isoformat()


def test_sixty_daily_seven_day_curves_for_four_stages_and_six_arms_fit_the_bound():
    caps = {f"i{index}": 5000 for index in range(4)}
    instance = archive(caps)
    for day in range(60):
        receipt = NOW + timedelta(days=day)
        points = tuple(point(receipt + timedelta(hours=hour), inverter=inverter)
                       for inverter in caps for hour in range(7 * 24))
        instance.capture({f"source{arm}": points for arm in range(6)}, calculated_at=receipt,
                         received_at=receipt, weather_issues={})
    diagnostics = instance.diagnostics()
    assert diagnostics["points"] == 60 * 7 * 24 * 4 * 6 == 241920
    assert diagnostics["snapshots"] == 360
    assert diagnostics["first_receipt"] == NOW.isoformat()
    # Compact arrays avoid per-point hash/key duplication in the private file.
    encoded = json.dumps(instance.to_dict(), separators=(",", ":"))
    assert len(encoded.encode()) < 40_000_000


def test_running_point_is_cropped_only_to_real_future_support_without_changing_mean():
    instance = archive()
    original = point(start=NOW - timedelta(minutes=30))
    capture(instance, NOW, points=[original])
    row = instance.snapshots[0]["points"][0]
    assert row[1] == NOW.isoformat()
    assert row[3] == original.start.isoformat()
    assert row[2] == original.end.isoformat() and row[4] == original.power_w
    records = forecast_records_from_comparison_archive(instance.to_dict(), [], as_of=NOW)
    assert records[0].issued_at == NOW  # Never promote the older weather issue.


@pytest.mark.parametrize("kind", ["bool", "over_cap", "future_receipt", "future_weather", "duplicate", "bad_binding"])
def test_malformed_comparison_branch_fails_closed(kind):
    instance = archive()
    capture(instance)
    data = instance.to_dict()
    row = data["snapshots"][0]
    if kind == "bool":
        row["points"][0][4] = True
    elif kind == "over_cap":
        row["points"][0][4] = 5001
    elif kind == "future_receipt":
        row["retrieved_at"] = (NOW + timedelta(seconds=1)).isoformat()
    elif kind == "future_weather":
        row["weather_issued_at"]["best_match"] = (NOW + timedelta(seconds=1)).isoformat()
    elif kind == "duplicate":
        data["snapshots"].append(deepcopy(row))
    else:
        data["config_fingerprint"] = "opaque"
    with pytest.raises(ValueError):
        ComparisonArchive.from_dict(data, as_of=NOW)


def test_comparison_bounds_prune_whole_snapshots_by_receipt_not_favorable_points(monkeypatch):
    instance = archive()
    monkeypatch.setattr(archive_module, "MAX_COMPARISON_POINTS", 3)
    for hour in range(5):
        capture(instance, NOW + timedelta(days=hour), points=[point(start=NOW + timedelta(days=hour + 1), power=hour)])
    assert len(instance.snapshots) == 3
    assert [row["points"][0][4] for row in instance.snapshots] == [2, 3, 4]
    instance.prune(NOW + timedelta(days=125))
    assert instance.snapshots == []


def test_newest_unavailable_or_partial_scope_never_falls_back_to_old_success():
    start, end = NOW + timedelta(days=2, hours=3), NOW + timedelta(days=2, hours=4)
    instance = archive({"i": 5000, "other": 5000})
    capture(instance, NOW, points=[point(start), point(start, inverter="other")])
    receipt = NOW + timedelta(days=1)
    capture(instance, receipt, points=[point(NOW + timedelta(days=3), inverter="other")])
    windows = [EvaluationWindow(receipt, start, end, inverter) for inverter in ("i", "other")]
    records = forecast_records_from_comparison_archive(instance.to_dict(), windows, as_of=receipt)
    actuals = [ActualRecord(start, end, inverter, 1000, end) for inverter in ("i", "other")]
    report = evaluate_forecasts(records, actuals, windows, as_of=end, sources=("adaptive",))
    assert report["paired_intervals"] == 0
    assert all(row["missing_sources"] == ["adaptive"] for row in report["missing"])
    assert any(row.power_w is None and row.inverter_id == "i" and row.issued_at == receipt for row in records)


def test_local_receipt_cannot_be_replaced_by_old_weather_issue_at_declared_cutoff():
    instance = archive()
    receipt = NOW + timedelta(minutes=5)
    capture(instance, receipt)
    target = point()
    window = EvaluationWindow(NOW, target.start, target.end, "i")
    records = forecast_records_from_comparison_archive(instance.to_dict(), [window], as_of=receipt)
    actual = ActualRecord(target.start, target.end, "i", 1000, target.end)
    report = evaluate_forecasts(records, [actual], [window], as_of=target.end, sources=("adaptive",))
    assert report["paired_intervals"] == 0


def native_comparison_writes(instance):
    store = instance._comparison_store

    async def write(data):
        await NATIVE_WRITE(store, data)

    store._async_write_data = write
    store.async_save = AsyncMock(wraps=store.async_save)


async def test_coordinator_archives_all_arms_in_separate_fixed_store(hass):
    instance = coordinator(hass)
    native_comparison_writes(instance)
    target = point()
    result = ForecastResult(NOW, (target,), member_points={"best_match": (replace(target, power_w=800),)},
                            member_issued_at={"best_match": NOW - timedelta(hours=1)})
    instance._shadow_archive_pending = (replace(target, power_w=950),)
    with freeze_time(NOW + timedelta(seconds=1)):
        await instance.async_restore()
        instance._archive_result(result, available_at=result.issued_at)
        instance.intervals = [measured()]
        stored = instance._stored()
        assert COMPARISON_ARCHIVE_KEY not in stored
        assert instance._comparison_store.key.endswith(".comparison_v1")
        assert instance._comparison_store._serialize_in_event_loop is False
        instance.async_commit_setup()
        await hass.async_block_till_done()
        assert instance._comparison_store.async_save.await_count == 1
        restored = coordinator(hass)
        restored._comparison_store = instance._comparison_store
        seed_store(restored._store, stored)
        await restored.async_restore()
    sources = {row["source"]: row for row in restored._comparison_archive.snapshots}
    assert set(sources) == {"adaptive", "operative_baseline", "shadow:early_bias", "nwp:best_match"}
    assert sources["operative_baseline"]["points"][0][4] == target.baseline_w
    assert sources["nwp:best_match"]["points"][0][4] == 800
    assert len(restored.archive) == 1
    assert restored.intervals == instance.intervals
    assert restored._comparison_archive.to_dict() == instance._comparison_archive.to_dict()
    with freeze_time(NOW + timedelta(seconds=1)):
        await instance.async_close()
        await restored.async_close()
    assert instance._comparison_store.async_save.await_count == 1


async def test_comparison_keeps_real_nwp_arm_when_all_operative_ghi_cells_fail(hass):
    from tests.test_engine import T, config, forecast, weather
    from custom_components.adaptive_solar.core.engine import ForecastEngine
    from custom_components.adaptive_solar.core.models import Observation

    cfg = replace(config(models=("best_match",)), physics_substeps=4, timezone="Pacific/Auckland")
    source = replace(weather(ghi=1000), dni_w_m2=1700)
    result = ForecastEngine(cfg).forecast((forecast("best_match", (source,)),), T,
                                          (Observation(T, "i", ghi_w_m2=1600),))
    assert not result.points
    instance = coordinator(hass)
    instance.site = cfg
    instance._comparison_archive = ComparisonArchive("a" * 64, "b" * 64, {"i": 5000}, cfg.timezone)
    with freeze_time(T):
        instance._capture_comparison(result, received_at=T)
        stored = instance._comparison_archive.to_dict()
        restored = ComparisonArchive.from_dict(stored, as_of=T)
    sources = {row["source"]: row for row in restored.snapshots}
    assert sources["adaptive"]["points"] == [] and sources["operative_baseline"]["points"] == []
    nwp = sources["nwp:best_match"]
    assert len(nwp["points"]) == 1 and nwp["points"][0][4] > 0
    assert nwp["weather_issued_at"]["best_match"] == T.isoformat()
    assert not instance.archive and not instance.intervals
    await instance.async_close()


@pytest.mark.parametrize("bad", ["invalid_json", "unknown_schema", "unknown_envelope"])
async def test_corrupt_comparison_store_is_preserved_without_blocking_meters(hass, bad):
    from pathlib import Path

    instance = coordinator(hass)
    instance.intervals = [measured()]
    stored = instance._stored()
    seed_store(instance._store, stored)
    path = Path(instance._comparison_store.path)
    path.parent.mkdir(parents=True, exist_ok=True)
    broken = {"version": 1, "minor_version": 1, "key": instance._comparison_store.key,
              "data": {"schema_version": 999}}
    if bad == "unknown_envelope":
        broken["version"] = 999
    original = b"{broken" if bad == "invalid_json" else json.dumps(broken).encode()
    path.write_bytes(original)
    instance._comparison_store.async_save = AsyncMock()
    with freeze_time(NOW):
        await instance.async_restore()
        assert instance.intervals == stored["intervals"] and instance._store_writable
        assert instance._comparison_archive.snapshots == []
        assert not instance._comparison_store_writable
        assert instance._comparison_storage_status == "invalid_store_preserved_read_only"
        instance._archive_comparison(ForecastResult(NOW, (point(),)))
        instance.async_commit_setup()
        await hass.async_block_till_done()
        await instance.async_close()
    instance._comparison_store.async_save.assert_not_awaited()
    assert path.read_bytes() == original
    assert not list(path.parent.glob(path.name + ".corrupt.*"))


async def test_failed_setup_never_writes_an_existing_or_new_comparison_store(hass):
    instance = coordinator(hass)
    instance._comparison_store.async_save = AsyncMock()
    with freeze_time(NOW):
        await instance.async_restore()
        instance._archive_comparison(ForecastResult(NOW, (point(),)))
        await hass.async_block_till_done()
        await instance.async_close()  # No async_commit_setup after a failed refresh/platform setup.
    instance._comparison_store.async_save.assert_not_awaited()


async def test_meter_save_cycles_do_not_rewrite_large_comparison_archive(hass):
    instance = coordinator(hass)
    native_comparison_writes(instance)
    with freeze_time(NOW):
        await instance.async_restore()
        instance.async_commit_setup()
        instance._archive_comparison(ForecastResult(NOW, (point(),)))
        await hass.async_block_till_done()
        receipt = instance._comparison_archive.snapshots[0]["retrieved_at"]
        assert instance._comparison_store.async_save.await_count == 1
        for _ in range(40):
            instance._schedule_save()
            assert COMPARISON_ARCHIVE_KEY not in instance._stored()
        instance._archive_comparison(ForecastResult(NOW, (replace(point(), power_w=2000),)))
        await hass.async_block_till_done()
        assert instance._comparison_store.async_save.await_count == 1
        assert instance._comparison_archive.snapshots[0]["retrieved_at"] == receipt
        await instance.async_close()
    assert instance._comparison_store.async_save.await_count == 1


async def test_silent_native_write_failure_keeps_revision_dirty_and_retries_original_receipt(hass):
    instance = coordinator(hass)
    native_comparison_writes(instance)
    original_save = instance._comparison_store.async_save
    instance._comparison_store.async_save = AsyncMock()  # Native Store may log and return after a disk error.
    with freeze_time(NOW):
        await instance.async_restore()
        instance.async_commit_setup()
        result = ForecastResult(NOW, (point(),))
        instance._archive_comparison(result)
        await hass.async_block_till_done()
        original = instance._comparison_archive.to_dict()
        assert instance._comparison_storage_status == "write_failed"
        assert instance._comparison_saved_revision != instance._comparison_archive.revision
        instance._comparison_store.async_save = original_save
        instance._archive_comparison(result)
        await hass.async_block_till_done()
        assert instance._comparison_storage_status == "writable"
        assert instance._comparison_saved_revision == instance._comparison_archive.revision
        assert instance._comparison_archive.to_dict() == original
        await instance.async_close()


async def test_prune_alone_saves_changed_archive_and_close_flushes_pending_capture(hass):
    instance = coordinator(hass)
    native_comparison_writes(instance)
    with freeze_time(NOW):
        await instance.async_restore()
        instance.async_commit_setup()
        instance._archive_comparison(ForecastResult(NOW, (point(),)))
        # Close waits for the already scheduled worker/native write.
        await instance.async_close()
    assert instance._comparison_store.async_save.await_count == 1
    restored = coordinator(hass)
    restored._comparison_store = instance._comparison_store
    with freeze_time(NOW + timedelta(days=121)):
        await restored.async_restore()
        assert restored._comparison_archive.snapshots == []
        restored.async_commit_setup()
        await hass.async_block_till_done()
        assert instance._comparison_store.async_save.await_count == 2
        await restored.async_close()
    assert instance._comparison_store.async_save.await_count == 2


async def test_optional_store_load_and_save_exceptions_do_not_abort_coordinator(hass, monkeypatch):
    instance = coordinator(hass)
    monkeypatch.setattr(instance, "_load_comparison", Mock(side_effect=OSError("read failure")))
    with freeze_time(NOW):
        await instance.async_restore()
        assert instance._store_writable and not instance._comparison_store_writable
        await instance.async_close()
    second = coordinator(hass)
    second._comparison_store.async_save = AsyncMock(side_effect=OSError("disk failure"))
    with freeze_time(NOW):
        await second.async_restore()
        second.async_commit_setup()
        second._archive_comparison(ForecastResult(NOW, (point(),)))
        await hass.async_block_till_done()
        assert second._comparison_storage_status == "write_failed"
        await second.async_close()


def test_evaluate_cli_reads_comparison_branch_and_preserves_input(offline_process, tmp_path):
    instance = archive()
    capture(instance)
    target = point()
    source, schedule, output = (tmp_path / name for name in ("comparison.json", "schedule.json", "report.json"))
    source.write_text(json.dumps({"data": {COMPARISON_ARCHIVE_KEY: instance.to_dict()}}))
    schedule.write_text(json.dumps({"as_of": target.end.isoformat(), "sources": ["adaptive"],
        "windows": [{"cutoff": NOW.isoformat(), "start": target.start.isoformat(),
                     "end": target.end.isoformat(), "inverter_id": "i"}],
        "actuals": [{"start": target.start.isoformat(), "end": target.end.isoformat(),
                     "inverter_id": "i", "power_w": 1000, "observed_at": target.end.isoformat()}]}))
    original = source.read_bytes()
    process = offline_process("evaluate.py", schedule, "--comparison-archive", source, "--output", output)
    assert process.returncode == 0, process.stderr
    report = json.loads(output.read_text())
    assert report["paired_intervals"] == 1 and not report["comparison_eligible"]
    assert source.read_bytes() == original
    process = offline_process("evaluate.py", schedule, "--comparison-archive", source, "--output", source)
    assert process.returncode != 0 and source.read_bytes() == original


async def test_native_logged_disk_error_does_not_mark_comparison_as_saved(hass, monkeypatch):
    from homeassistant.helpers.storage import WriteError

    instance = coordinator(hass)
    native_comparison_writes(instance)
    prepared_write = instance._comparison_store._write_prepared_data
    monkeypatch.setattr(instance._comparison_store, "_write_prepared_data", Mock(side_effect=WriteError("disk unavailable")))
    with freeze_time(NOW):
        await instance.async_restore()
        instance.async_commit_setup()
        result = ForecastResult(NOW, (point(),))
        instance._archive_comparison(result)
        await hass.async_block_till_done()
        assert instance._comparison_storage_status == "write_failed"
        assert instance._comparison_saved_revision != instance._comparison_archive.revision
        receipt = instance._comparison_archive.snapshots[0]["retrieved_at"]
        monkeypatch.setattr(instance._comparison_store, "_write_prepared_data", prepared_write)
        instance._archive_comparison(result)
        await hass.async_block_till_done()
        assert instance._comparison_saved_revision == instance._comparison_archive.revision
        assert instance._comparison_archive.snapshots[0]["retrieved_at"] == receipt
        await instance.async_close()


async def test_valid_configuration_change_preserves_original_until_setup_and_new_capture(hass):
    from pathlib import Path

    instance = coordinator(hass)
    native_comparison_writes(instance)
    old = ComparisonArchive("f" * 64, instance._history_fingerprint,
                            {inv.id: inv.output_cap_w for inv in instance.site.inverters}, instance.site.timezone)
    with freeze_time(NOW):
        capture(old)
        envelope = {"version": 1, "minor_version": 1, "key": instance._comparison_store.key, "data": old.to_dict()}
        path = Path(instance._comparison_store.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        original = json.dumps(envelope).encode()
        path.write_bytes(original)
        await instance.async_restore()
        assert instance._comparison_store_writable and instance._comparison_archive.snapshots == []
        assert instance._comparison_archive.restore_status == "configuration_changed_new_archive"
        instance.async_commit_setup()
        await hass.async_block_till_done()
        assert path.read_bytes() == original
        instance._archive_comparison(ForecastResult(NOW, (point(),)))
        await hass.async_block_till_done()
        assert json.loads(path.read_bytes())["data"]["config_fingerprint"] == instance._fingerprint
        await instance.async_close()


@pytest.mark.parametrize("failure", ["weather", "calculation"])
async def test_failed_daily_first_attempt_blocks_older_success_and_later_replacement(hass, monkeypatch, failure):
    from homeassistant.helpers.update_coordinator import UpdateFailed
    from custom_components.adaptive_solar.core.models import WeatherForecast, WeatherPoint
    from custom_components.adaptive_solar.weather import WeatherError

    instance = coordinator(hass)
    native_comparison_writes(instance)
    target = NOW + timedelta(days=2, hours=1)
    weather_point = WeatherPoint(target, target + timedelta(hours=1), 500, 600, 100, 20, 2, 30)
    instance.client.async_forecasts.return_value = (WeatherForecast("best_match", NOW, (weather_point,)),)
    with freeze_time(NOW):
        await instance.async_restore()
        previous = await instance._async_update_data()
        assert previous.points
        instance.async_commit_setup()
        await hass.async_block_till_done()
    failure_time = NOW + timedelta(days=1)
    original_forecast = instance.engine.forecast
    if failure == "weather":
        instance.client.async_forecasts.side_effect = WeatherError("all providers failed")
        expected_error = UpdateFailed
    else:
        instance.client.async_forecasts.return_value = (WeatherForecast("best_match", failure_time, (weather_point,)),)
        monkeypatch.setattr(instance.engine, "forecast", Mock(side_effect=RuntimeError("mandatory physics failure")))
        expected_error = RuntimeError
    with freeze_time(failure_time):
        with pytest.raises(expected_error):
            await instance._async_update_data()
        await hass.async_block_till_done()
        unavailable = [row for row in instance._comparison_archive.snapshots
                       if row["retrieved_at"] == failure_time.isoformat()]
        assert {row["source"] for row in unavailable} == {
            "adaptive", "operative_baseline", "shadow:early_bias", "nwp:best_match"}
        assert all(row["status"] == "unavailable" and row["points"] == [] for row in unavailable)
        window = EvaluationWindow(failure_time, target, target + timedelta(hours=1), "i")
        records = forecast_records_from_comparison_archive(instance._comparison_archive.to_dict(), [window], as_of=failure_time)
        assert any(row.source == "adaptive" and row.issued_at == failure_time and row.power_w is None for row in records)
        actual = ActualRecord(target, target + timedelta(hours=1), "i", 1000, target + timedelta(hours=1))
        report = evaluate_forecasts(records, [actual], [window], as_of=actual.observed_at, sources=("adaptive",))
        assert report["paired_intervals"] == 0 and report["missing"][0]["missing_sources"] == ["adaptive"]
        frozen_failure = deepcopy(unavailable)
    later = failure_time + timedelta(minutes=5)
    with freeze_time(later):
        instance.client.async_forecasts.side_effect = None
        instance.client.async_forecasts.return_value = (WeatherForecast("best_match", later, (weather_point,)),)
        monkeypatch.setattr(instance.engine, "forecast", original_forecast)
        assert (await instance._async_update_data()).points
        assert [row for row in instance._comparison_archive.snapshots
                if row["retrieved_at"] == failure_time.isoformat()] == frozen_failure
        assert not any(row["retrieved_at"] == later.isoformat() for row in instance._comparison_archive.snapshots)
        await instance.async_close()


@pytest.mark.parametrize("closing", [False, True])
async def test_cancelled_or_unloading_forecast_does_not_archive_a_failed_attempt(hass, closing):
    import asyncio

    from custom_components.adaptive_solar.weather import WeatherError

    instance = coordinator(hass)
    with freeze_time(NOW):
        await instance.async_restore()
        instance._closing = closing
        instance.client.async_forecasts.side_effect = WeatherError("unloading") if closing else asyncio.CancelledError
        with pytest.raises(BaseException):
            await instance._async_update_data()
        assert instance._comparison_archive.snapshots == []
        await instance.async_close()


@pytest.mark.parametrize("existing_symlink", [True, False])
async def test_comparison_loader_distinguishes_dangling_symlink_from_missing_store(hass, existing_symlink):
    from pathlib import Path

    instance = coordinator(hass)
    native_comparison_writes(instance)
    path = Path(instance._comparison_store.path)
    target = path.with_name("missing-comparison-target.json")
    if existing_symlink:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(target)
        assert path.is_symlink() and not path.exists()
    with freeze_time(NOW):
        await instance.async_restore()
        assert instance._comparison_store_writable is (not existing_symlink)
        assert instance._comparison_storage_status == (
            "invalid_store_preserved_read_only" if existing_symlink else "writable")
        instance._capture_comparison(ForecastResult(NOW, (point(),)), received_at=NOW)
        instance.async_commit_setup()
        instance._schedule_save()
        if existing_symlink:
            await instance._async_save_comparison()
        await hass.async_block_till_done()
        await instance.async_close()
    if existing_symlink:
        instance._comparison_store.async_save.assert_not_awaited()
        assert path.is_symlink() and path.readlink() == target
        assert not target.exists()
    else:
        assert instance._comparison_store.async_save.await_count == 1
        assert path.is_file() and not path.is_symlink()
        assert json.loads(path.read_bytes())["data"]["snapshots"]


async def test_primary_dangling_symlink_also_blocks_legacy_save_and_snapshot_import(hass):
    from pathlib import Path

    instance = coordinator(hass)
    seed_store(instance._legacy_store, {**instance._stored(), "intervals": [measured()]})
    path = Path(instance._store.path)
    target = path.with_name("missing-primary-target.json")
    path.symlink_to(target)
    instance._store.async_save = AsyncMock()
    with freeze_time(NOW):
        await instance.async_restore()
        assert not instance._store_writable and instance.intervals == []
        assert instance._history_storage_status == "invalid_primary_preserved_read_only"
        instance.async_commit_setup()
        with pytest.raises(ValueError, match="persistence is not writable"):
            await instance.async_restore_day_start(NOW.date().isoformat(), {}, instance.site)
        instance._schedule_save()
        await hass.async_block_till_done()
        await instance.async_close()
    instance._store.async_save.assert_not_awaited()
    assert path.is_symlink() and path.readlink() == target and not target.exists()
