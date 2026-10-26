"""Feature-contract migration preserves separately validated measured evidence."""
from datetime import UTC, datetime, timedelta
from dataclasses import replace
from unittest.mock import AsyncMock, Mock, patch

from freezegun import freeze_time
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_solar.coordinator import AdaptiveSolarCoordinator, join_training
from custom_components.adaptive_solar.core.models import InverterConfig, SiteConfig, StringConfig
from custom_components.adaptive_solar.core.models import WeatherForecast, WeatherPoint
from custom_components.adaptive_solar.weather import WeatherError

NOW = datetime(2026, 6, 1, 10, tzinfo=UTC)


def coordinator(hass, entry=None, config=None):
    config = config or SiteConfig(52, 13, "Europe/Berlin", (StringConfig("s", "i", 5, 30, 180),), (InverterConfig("i", 5),))
    if entry is None:
        entry = MockConfigEntry(domain="adaptive_solar", data={"site": config.to_dict()})
        entry.add_to_hass(hass)
    return AdaptiveSolarCoordinator(hass, entry, config, AsyncMock()), entry


def evidence(instance):
    start, end = NOW.isoformat(), (NOW + timedelta(hours=1)).isoformat()
    nwp = {"issued_at": (NOW - timedelta(hours=1)).isoformat(), "start": start, "end": end,
           "inverter_id": "i", "baseline_w": 2000,
           "features": {"baseline_w": 2000, "sun_elevation_deg": 45, "lead_hours": 1.5}}
    ghi = {**nwp, "issued_at": (NOW - timedelta(minutes=30)).isoformat(),
           "features": {**nwp["features"], "ghi_regime": 1.0, "ghi_nowcast_gain": 0.8,
                        "ghi_observation_age_seconds": 0.0, "ghi_observation_w_m2": 600.0}}
    return {"fingerprint": instance._fingerprint, "archive": [nwp, ghi],
            "intervals": [{"inverter_id": "i", "start": start, "end": end,
                           "observed_at": end, "energy_kwh": 1.0}],
            "daily_snapshots": {"2026-06-01": {"issued_at": "2026-05-31T21:00:00+00:00", "energies": {"i": 24.0}}}}


@pytest.mark.parametrize("marker", ["missing", None, "legacy-features", "atomic-ghi-cohort-centered-weather-v1", "atomic-ghi-cohort-centered-weather-v2", True, 1, []])
async def test_incompatible_learning_contract_cold_starts_features_only(hass, marker):
    instance, entry = coordinator(hass)
    payload = evidence(instance)
    if marker != "missing":
        payload["learning_feature_contract"] = marker
    instance._legacy_store.async_load = AsyncMock(return_value=payload)
    instance._learner, instance._fit_signature = object(), (42, NOW.date())
    instance.learner_status = {"i": {"state": "active"}}
    with freeze_time(NOW + timedelta(hours=2)):
        await instance.async_restore()
        assert instance.archive == []
        assert instance._learner is instance._fit_signature is None
        assert instance.learner_status == {}
        assert instance.intervals == payload["intervals"]
        assert instance.daily_snapshots == payload["daily_snapshots"]
        assert join_training(instance.archive, instance.intervals) == []
        assert instance.tracker.anchors == {}
        assert instance._stored()["learning_feature_contract"]
        instance.async_commit_setup()
        await instance.async_close()
        # Saving the migrated payload cannot reintroduce its old feature rows.
        restored, _ = coordinator(hass, entry)
        await restored.async_restore()
        assert restored.archive == []
        assert restored.intervals == payload["intervals"]
        assert restored.daily_snapshots == payload["daily_snapshots"]
        await restored.async_close()


@freeze_time(NOW + timedelta(hours=2))
async def test_current_learning_contract_roundtrip_preserves_both_regimes_and_actuals(hass):
    instance, entry = coordinator(hass)
    payload = evidence(instance)
    instance.archive, instance.intervals, instance.daily_snapshots = payload["archive"], payload["intervals"], payload["daily_snapshots"]
    marker = instance._stored()["learning_feature_contract"]
    assert isinstance(marker, str) and marker
    original_config, original_fingerprint = instance.site.to_dict(), instance._fingerprint
    with freeze_time(NOW + timedelta(hours=2)):
        await instance.async_restore()
        instance.async_commit_setup()
        await instance.async_close()
        restored, _ = coordinator(hass, entry)
        await restored.async_restore()
        assert restored.archive == payload["archive"]
        assert restored.intervals == payload["intervals"]
        assert restored.daily_snapshots == payload["daily_snapshots"]
        assert restored._stored()["learning_feature_contract"] == marker
        assert restored.site.to_dict() == original_config
        assert restored._fingerprint == original_fingerprint
        assert len(join_training(restored.archive, restored.intervals)) == 2
        await restored.async_close()


@pytest.mark.parametrize("legacy", [False, True])
async def test_control_upgrade_retains_old_evidence_without_certifying_it(hass, legacy):
    config = SiteConfig(52, 13, "Europe/Berlin", (StringConfig("s", "i", 5, 30, 180),),
                        (InverterConfig("i", 5, curtailed_entity_id="binary_sensor.control"),))
    instance, entry = coordinator(hass, config=config)
    payload = {**instance._stored(), **evidence(instance)}
    store = instance._legacy_store if legacy else instance._store
    await store.async_save(payload)
    with freeze_time(NOW + timedelta(hours=2)):
        await instance.async_restore()
        assert instance.intervals == payload["intervals"]
        assert instance.archive == payload["archive"]
        assert instance.daily_snapshots == payload["daily_snapshots"]
        assert "curtailment_measurement_contract" not in instance.intervals[0]
        instance.async_commit_setup()
        await instance.async_close()
        restored, _ = coordinator(hass, entry, config)
        await restored.async_restore()
        assert restored.intervals == payload["intervals"]
        assert "curtailment_measurement_contract" not in restored.intervals[0]
        await restored.async_close()


async def test_obsolete_feature_structure_cannot_discard_valid_independent_evidence(hass):
    instance, _ = coordinator(hass)
    payload = evidence(instance)
    payload["archive"] = {"obsolete_feature_structure": True}
    instance._legacy_store.async_load = AsyncMock(return_value=payload)
    with freeze_time(NOW + timedelta(hours=2)):
        await instance.async_restore()
    assert instance.archive == []
    assert instance.intervals == payload["intervals"]
    assert instance.daily_snapshots == payload["daily_snapshots"]
    await instance.async_close()


async def saved_history(hass):
    instance, entry = coordinator(hass)
    await instance.async_restore()
    payload = {**evidence(instance), "learning_feature_contract": instance._stored()["learning_feature_contract"]}
    instance.archive, instance.intervals, instance.daily_snapshots = payload["archive"], payload["intervals"], payload["daily_snapshots"]
    for idx in range(5):
        instance.shading.record("i", 180.0, 40.0, NOW - timedelta(hours=2, minutes=15 * idx), 0.6)
    instance.async_commit_setup()
    await instance.async_close()
    return instance, entry, payload


@pytest.mark.parametrize("change", ["temperature", "wind", "irradiance", "power", "weather", "days"])
async def test_observation_and_weather_changes_preserve_actuals_and_published_day_start(hass, change):
    with freeze_time(NOW + timedelta(hours=2)):
        first, entry, payload = await saved_history(hass)
        updates = {f"{change}_entity_id": f"sensor.{change}"} if change in {"temperature", "wind", "irradiance"} else {}
        if change == "power":
            updates["inverters"] = (replace(first.site.inverters[0], power_entity_id="sensor.new_power"),)
        elif change == "weather":
            updates["weather_models"] = ("icon_d2",)
        elif change == "days":
            updates["forecast_days"] = 3
        second, _ = coordinator(hass, entry, replace(first.site, **updates))
        await second.async_restore()
        assert second._fingerprint != first._fingerprint
        assert second._history_fingerprint == first._history_fingerprint
        assert second.archive == []
        assert second.intervals == payload["intervals"]
        assert second.daily_snapshots == payload["daily_snapshots"]
        assert second.tracker.anchors == {}
        if change == "days":
            assert second._shade_fingerprint == first._shade_fingerprint
            assert second.shading.transmittance("i", 180.0, 40.0) == pytest.approx(0.6)
        else:
            assert second._shade_fingerprint != first._shade_fingerprint
            assert second.shading.to_dict() == {"schema": 1, "inverters": {}}
        second.async_commit_setup()
        await second.async_close()
        third, _ = coordinator(hass, entry, second.site)
        await third.async_restore()
        assert third.intervals == payload["intervals"] and third.daily_snapshots == payload["daily_snapshots"]
        if change == "days":
            assert third.shading.transmittance("i", 180.0, 40.0) == pytest.approx(0.6)
        else:
            assert third.shading.to_dict() == {"schema": 1, "inverters": {}}
        await third.async_close()


@pytest.mark.parametrize("change", ["physical", "timezone", "energy", "curtailment", "boundary"])
async def test_known_physical_or_label_source_change_never_reuses_history(hass, change):
    with freeze_time(NOW + timedelta(hours=2)):
        first, entry, _ = await saved_history(hass)
        options = {"latitude": 53} if change == "physical" else {"timezone": "UTC"} if change == "timezone" else {}
        if change in {"energy", "curtailment"}:
            key = "energy_entity_id" if change == "energy" else "curtailed_entity_id"
            options["inverters"] = (replace(first.site.inverters[0], **{key: "sensor.new_binding"}),)
        elif change == "boundary":
            options["inverters"] = (InverterConfig("i", output_type="dc", max_output_kw=5),)
        changed, _ = coordinator(hass, entry, replace(first.site, **options))
        await changed.async_restore()
        assert changed.archive == changed.intervals == [] and changed.daily_snapshots == {}
        assert changed._store.key == first._store.key  # One bounded new primary, no per-config files.
        await changed.async_close()  # Uncommitted/failed setup cannot replace it.
        original, _ = coordinator(hass, entry, first.site)
        await original.async_restore()
        assert original.intervals and original.daily_snapshots
        await original.async_close()


async def test_opaque_foreign_legacy_payload_is_preserved_even_after_new_setup_commit(hass):
    instance, entry = coordinator(hass)
    foreign = {**evidence(instance), "fingerprint": "unprovable-legacy-config"}
    await instance._legacy_store.async_save(foreign)
    with freeze_time(NOW + timedelta(hours=2)):
        await instance.async_restore()
        assert instance.archive == instance.intervals == [] and instance.daily_snapshots == {}
        instance.async_commit_setup()
        await instance.async_close()
    fresh, _ = coordinator(hass, entry)
    assert await fresh._legacy_store.async_load() == foreign
    assert await fresh._store.async_load() is not None
    await fresh.async_close()


@pytest.mark.parametrize("invalid", ["schema", "energy"])
async def test_unrecognized_or_corrupt_primary_is_never_overwritten(hass, invalid):
    instance, entry = coordinator(hass)
    payload = {**instance._stored(), **evidence(instance)}
    if invalid == "schema":
        payload["history_schema"] = True
    else:
        payload["intervals"][0]["energy_kwh"] = True
    await instance._store.async_save(payload)
    with freeze_time(NOW + timedelta(hours=2)):
        await instance.async_restore()
        assert instance.archive == instance.intervals == [] and instance.daily_snapshots == {}
        instance.async_commit_setup()
        assert not instance._persistence_active and not instance._save_pending
        await instance.async_close()
    fresh, _ = coordinator(hass, entry)
    assert await fresh._store.async_load() == payload
    await fresh.async_close()


@pytest.mark.parametrize("failure", ["weather", "platform"])
async def test_real_failed_reload_never_schedules_or_saves_over_existing_history(hass, enable_custom_integrations, failure):
    with freeze_time(NOW + timedelta(hours=2)):
        first, entry, _ = await saved_history(hass)
        before = await first._store.async_load()
        changed = replace(first.site, irradiance_entity_id="sensor.new_ghi")
        hass.config_entries.async_update_entry(entry, options={"site": changed.to_dict()})
        created = []

        def create(*args, **kwargs):
            instance = AdaptiveSolarCoordinator(*args, **kwargs)
            instance._store.async_save = AsyncMock(wraps=instance._store.async_save)
            instance._store.async_delay_save = Mock(wraps=instance._store.async_delay_save)
            created.append(instance)
            return instance

        weather = WeatherForecast("best_match", NOW + timedelta(hours=2), (
            WeatherPoint(NOW + timedelta(hours=2), NOW + timedelta(hours=3), 600, 400, 200, 20, 2, 30),))
        with patch("custom_components.adaptive_solar.coordinator.AdaptiveSolarCoordinator", side_effect=create), \
             patch("custom_components.adaptive_solar.weather.OpenMeteoClient.async_forecasts", new=AsyncMock(
                 side_effect=WeatherError("unavailable") if failure == "weather" else None, return_value=(weather,))), \
             patch.object(hass.config_entries, "async_forward_entry_setups", new=AsyncMock(side_effect=RuntimeError("platform failure"))):
            assert await hass.config_entries.async_setup(entry.entry_id) is False
            await hass.async_block_till_done()
        created[0]._store.async_save.assert_not_called()
        created[0]._store.async_delay_save.assert_not_called()
        assert created[0]._unsub is None and created[0]._unsub_reports is None
        untouched, _ = coordinator(hass, entry, first.site)
        assert await untouched._store.async_load() == before
        await untouched.async_close()


async def test_beam_shade_v1_persistence_contract_migration_and_corrupt_table_recovery(hass):
    from custom_components.adaptive_solar.coordinator import LEARNING_FEATURE_CONTRACT
    from custom_components.adaptive_solar.core.shading import BEAM_SHADE_STORE_KEY, BeamShadeTable

    assert LEARNING_FEATURE_CONTRACT == "beam-shade-table-v1"
    instance, entry = coordinator(hass)
    table = BeamShadeTable()
    for idx in range(5):
        table.record("i", 180.0, 40.0, NOW - timedelta(days=200, minutes=15 * idx), 0.6)
    base = {**instance._stored(), **evidence(instance), "learning_feature_contract": LEARNING_FEATURE_CONTRACT}
    # 1. Missing beam_shade_v1 key loads empty table and keeps intervals/snapshots/archive.
    without_key = {k: v for k, v in base.items() if k != BEAM_SHADE_STORE_KEY}
    await instance._store.async_save(without_key)
    with freeze_time(NOW + timedelta(hours=2)):
        await instance.async_restore()
        assert instance.shading.to_dict() == {"schema": 1, "inverters": {}}
        assert instance.intervals == base["intervals"]
        assert instance.archive == base["archive"]
    await instance.async_close()
    # 2. Corrupt beam_shade_v1 loads empty table without discarding valid primary.
    corrupt_shade = {**base, BEAM_SHADE_STORE_KEY: {"schema": 1, "inverters": {"i": {"bad": "data"}}}}
    second, _ = coordinator(hass, entry)
    await second._store.async_save(corrupt_shade)
    with freeze_time(NOW + timedelta(hours=2)):
        await second.async_restore()
        assert second.shading.to_dict() == {"schema": 1, "inverters": {}}
        assert second.intervals == base["intervals"]
        assert second.archive == base["archive"]
        assert second.daily_snapshots == base["daily_snapshots"]
    await second.async_close()
    # 3. Contract upgrade to beam-shade-table-v1 discards old archive features but keeps intervals, snapshots and valid shade table.
    contract_upgrade = {
        **base,
        "learning_feature_contract": "atomic-ghi-cohort-centered-weather-v2",
        BEAM_SHADE_STORE_KEY: table.to_dict(),
    }
    third, _ = coordinator(hass, entry)
    await third._store.async_save(contract_upgrade)
    with freeze_time(NOW + timedelta(hours=2)):
        await third.async_restore()
        assert third.archive == []
        assert third.intervals == base["intervals"]
        assert third.daily_snapshots == base["daily_snapshots"]
        assert third.shading.transmittance("i", 182.0, 42.0) == pytest.approx(0.6)
        # Pruning at NOW+2h retains the 24-sample shade ring buffer independently of 120-day archive/interval cutoff.
        third._prune(NOW + timedelta(hours=2))
        assert third.shading.transmittance("i", 182.0, 42.0) == pytest.approx(0.6)
    await third.async_close()
    # 4. Physical history_fingerprint change discards primary and shade table.
    with freeze_time(NOW + timedelta(hours=2)):
        changed, _ = coordinator(hass, entry, replace(instance.site, latitude=53))
        await changed.async_restore()
        assert changed.archive == changed.intervals == []
        assert changed.shading.to_dict() == {"schema": 1, "inverters": {}}
        await changed.async_close()


async def test_save_enforces_retention_without_a_weather_refresh_and_restores(hass, monkeypatch):
    monkeypatch.setattr("custom_components.adaptive_solar.coordinator.MAX_TRAINING_ROWS", 2)
    with freeze_time(NOW + timedelta(hours=2)):
        instance, entry = coordinator(hass)
        await instance.async_restore()
        payload = evidence(instance)
        instance.daily_snapshots = payload["daily_snapshots"]
        row = payload["intervals"][0]
        # Directly exercise the serialization boundary, including retention of
        # old rows when no weather refresh has succeeded for a long time.
        instance.intervals = [
            {**row, "start": (NOW - timedelta(days=121)).isoformat(),
             "end": (NOW - timedelta(days=121) + timedelta(hours=1)).isoformat()},
            row,
            {**row, "start": (NOW + timedelta(hours=1)).isoformat(),
             "end": (NOW + timedelta(hours=1, minutes=30)).isoformat(), "observed_at": (NOW + timedelta(hours=2)).isoformat()},
        ]
        instance.async_commit_setup()
        await instance.async_close()
        restored, _ = coordinator(hass, entry)
        await restored.async_restore()
        assert len(restored.intervals) == 2
        assert restored.daily_snapshots == payload["daily_snapshots"]
        assert restored._store_writable
        # Pruning rebuilt the coalescing index: a later adjacent piece merges
        # into the right retained row, without overwriting its neighbor.
        restored._append_interval({**row, "start": (NOW + timedelta(hours=1, minutes=30)).isoformat(),
                                  "end": (NOW + timedelta(hours=1, minutes=35)).isoformat(),
                                  "observed_at": (NOW + timedelta(hours=2, minutes=5)).isoformat(),
                                  "energy_kwh": 0.1})
        assert len(restored.intervals) == 2
        assert restored.intervals[-1]["energy_kwh"] == 1.1
        await restored.async_close()


async def test_worker_snapshot_revision_refits_after_intervening_meter_report(hass, monkeypatch):
    instance, _ = coordinator(hass)
    instance.client.async_forecasts.return_value = (
        WeatherForecast("best_match", NOW, (
            WeatherPoint(NOW, NOW + timedelta(hours=1), 600, 400, 200, 20, 2, 30),)),)
    payload = evidence(instance)
    instance.archive = payload["archive"]
    original_executor = hass.async_add_executor_job
    handed_over = False

    def executor_with_report(fn, *args):
        nonlocal handed_over
        if not handed_over:
            handed_over = True
            instance._append_interval(payload["intervals"][0])
        return original_executor(fn, *args)

    monkeypatch.setattr(hass, "async_add_executor_job", executor_with_report)
    with freeze_time(NOW + timedelta(hours=2)), patch(
        "custom_components.adaptive_solar.coordinator.ResidualLearner.fit", autospec=True
    ) as fit:
        await instance._async_update_data()
        assert fit.call_count == 1
        assert fit.call_args.args[1] == []
        # The next refresh sees the report, without needing another event/day.
        await instance._async_update_data()
        assert fit.call_count == 2
        assert len(fit.call_args.args[1]) == 2
        await instance._async_update_data()
        assert fit.call_count == 2
    await instance.async_close()


@pytest.mark.parametrize("cross_hour", [False, True])
async def test_extra_meter_interval_at_limit_survives_weather_failure_and_restart(hass, monkeypatch, cross_hour):
    from homeassistant.helpers.update_coordinator import UpdateFailed

    monkeypatch.setattr("custom_components.adaptive_solar.coordinator.MAX_TRAINING_ROWS", 2)
    with freeze_time(NOW + timedelta(hours=2)):
        instance, entry = coordinator(hass)
        await instance.async_restore()
        instance.daily_snapshots = evidence(instance)["daily_snapshots"]
        for start_minute, end_minute in ((0, 5), (10, 15), (59, 61) if cross_hour else (20, 25)):
            instance._append_interval({"inverter_id": "i", "start": (NOW + timedelta(minutes=start_minute)).isoformat(),
                                      "end": (NOW + timedelta(minutes=end_minute)).isoformat(),
                                      "observed_at": (NOW + timedelta(hours=2)).isoformat(), "energy_kwh": 0.01})
        assert len(instance.intervals) == 2
        instance.client.async_forecasts.side_effect = WeatherError("weather unavailable")
        with pytest.raises(UpdateFailed, match="weather unavailable"):
            await instance._async_update_data()
        expected = [dict(row) for row in instance.intervals]
        instance.async_commit_setup()
        await instance.async_close()
        restored, _ = coordinator(hass, entry)
        await restored.async_restore()
        assert restored.intervals == expected
        assert restored.daily_snapshots
        assert restored._store_writable
        await restored.async_close()
