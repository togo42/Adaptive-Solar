"""Meter lineage, HA state events, persistence and CPU handoff tests."""
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from freezegun import freeze_time
import pytest
from homeassistant.core import State
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_solar.coordinator import AdaptiveSolarCoordinator, EnergyIntervalTracker, join_training, state_number
from custom_components.adaptive_solar.core.models import ForecastPoint, ForecastResult, InverterConfig, SiteConfig, StringConfig, WeatherForecast, WeatherPoint

NOW = datetime(2026, 6, 1, 10, tzinfo=UTC)


def site():
    return SiteConfig(52, 13, "Europe/Berlin", (StringConfig("s", "i", 5, 30, 180),), (InverterConfig("i", 5, energy_entity_id="sensor.energy", power_entity_id="sensor.power", curtailed_entity_id="binary_sensor.curtailed"),))


def archived():
    return {"issued_at": (NOW - timedelta(hours=1)).isoformat(), "start": NOW.isoformat(), "end": (NOW + timedelta(hours=1)).isoformat(), "inverter_id": "i", "baseline_w": 2000, "features": {"baseline_w": 2000, "lead_hours": 1.5, "sun_elevation_deg": 45}}


def test_real_energy_means_reset_gaps_and_whole_interval_curtailment():
    tracker = EnergyIntervalTracker()
    assert tracker.record("i", NOW, 10, True, 5000) is None
    row = tracker.record("i", NOW + timedelta(minutes=5), 10.1, True, 5000)
    assert row["energy_kwh"] == pytest.approx(0.1)
    assert join_training([archived()], [row, row]) == []  # a 5-minute mean cannot label the hour
    tracker.invalidate("i")
    assert tracker.record("i", NOW + timedelta(minutes=10), 10.2, True, 5000) is None
    assert tracker.record("i", NOW + timedelta(minutes=15), 0.01, True, 5000) is None  # reset
    assert tracker.record("i", NOW + timedelta(minutes=40), 0.02, True, 5000) is None  # gap
    assert tracker.record("i", NOW + timedelta(minutes=45), 0.03, False, 5000) is None
    assert tracker.record("i", NOW + timedelta(minutes=50), 0.04, True, 5000) is None
    assert tracker.record("i", NOW + timedelta(minutes=55), 0.05, True, 5000) is not None


@pytest.mark.parametrize("offset_seconds", [-60, 0])
@pytest.mark.parametrize("energy,safe", [(9.0, True), (11.0, True), (None, True), (10.0, False)])
def test_nonforward_meter_event_preserves_anchor_and_next_measured_delta(offset_seconds, energy, safe):
    tracker = EnergyIntervalTracker()
    tracker.record("i", NOW, 10, True, 5000)
    assert tracker.record("i", NOW + timedelta(seconds=offset_seconds), energy, safe, 5000) is None
    assert tracker.anchors["i"] == (NOW, 10)
    row = tracker.record("i", NOW + timedelta(minutes=5), 10.1, True, 5000)
    assert row["start"] == NOW.isoformat()
    assert row["end"] == (NOW + timedelta(minutes=5)).isoformat()
    assert row["energy_kwh"] == pytest.approx(0.1)


def test_nonforward_meter_event_cannot_clear_pending_curtailment_invalidation():
    tracker = EnergyIntervalTracker()
    tracker.record("i", NOW, 10, True, 5000)
    tracker.invalidate("i")
    assert tracker.record("i", NOW, 9, True, 5000) is None
    assert "i" in tracker.dirty
    assert tracker.record("i", NOW + timedelta(minutes=5), 10.1, True, 5000) is None
    row = tracker.record("i", NOW + timedelta(minutes=10), 10.2, True, 5000)
    assert row["start"] == (NOW + timedelta(minutes=5)).isoformat()
    assert row["energy_kwh"] == pytest.approx(0.1)


def test_forward_meter_reset_reanchors_without_label_and_keeps_cap_check():
    tracker = EnergyIntervalTracker()
    tracker.record("i", NOW, 10, True, 5000)
    reset = NOW + timedelta(minutes=5)
    assert tracker.record("i", reset, 0.01, True, 5000) is None
    assert tracker.anchors["i"] == (reset, 0.01)
    row = tracker.record("i", NOW + timedelta(minutes=10), 0.11, True, 5000)
    assert row["start"] == reset.isoformat()
    assert row["energy_kwh"] == pytest.approx(0.1)
    # A strictly newer grossly implausible delta still cannot become a label.
    assert tracker.record("i", NOW + timedelta(minutes=15), 2.11, True, 5000) is None


async def test_delayed_older_ha_state_cannot_bias_an_otherwise_eligible_training_hour(hass):
    config = site()
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    coordinator = AdaptiveSolarCoordinator(hass, entry, config, AsyncMock())
    with freeze_time(NOW + timedelta(minutes=1)):
        hass.states.async_set("binary_sensor.curtailed", "off")
        coordinator.async_start_tracking()
        hass.states.async_set("sensor.energy", "10", {"unit_of_measurement": "kWh"})
        await hass.async_block_till_done()
    old = hass.states.get("sensor.energy")
    # A fresh delivery can carry an older measurement timestamp. Its fictitious
    # delta would pass the power cap and make a biased full-hour label pre-fix.
    delayed = State("sensor.energy", "9.9", {"unit_of_measurement": "kWh"}, last_updated=NOW, last_reported=NOW)
    with freeze_time(NOW + timedelta(minutes=2)):
        hass.bus.async_fire("state_changed", {"entity_id": "sensor.energy", "old_state": old, "new_state": delayed})
        await hass.async_block_till_done()
    for minute in range(5, 61, 5):
        with freeze_time(NOW + timedelta(minutes=minute)):
            hass.states.async_set("sensor.energy", str(10 + (minute - 1) * 0.02), {"unit_of_measurement": "kWh"})
            await hass.async_block_till_done()
    assert len(coordinator.intervals) == 1
    measured = coordinator.intervals[0]
    assert measured["start"] == (NOW + timedelta(minutes=1)).isoformat()
    assert measured["end"] == (NOW + timedelta(hours=1)).isoformat()
    assert measured["energy_kwh"] == pytest.approx(1.18)
    sample = join_training([archived()], coordinator.intervals)[0]
    assert sample.actual_w == pytest.approx(1200)
    assert sample.features["measurement_coverage_fraction"] == pytest.approx(59 / 60)
    await coordinator.async_close()


def test_join_rejects_late_issue_and_hour_crossing_without_splitting_energy():
    tracker = EnergyIntervalTracker()
    tracker.record("i", NOW - timedelta(minutes=2), 10, True, 5000)
    crossing = tracker.record("i", NOW + timedelta(minutes=2), 10.1, True, 5000)
    assert join_training([archived()], [crossing]) == []
    row = {**archived(), "issued_at": (NOW + timedelta(minutes=1)).isoformat()}
    tracker.record("i", NOW + timedelta(minutes=5), 10.2, True, 5000)
    measured = tracker.record("i", NOW + timedelta(minutes=10), 10.3, True, 5000)
    assert join_training([row], [measured]) == []


def test_units_freshness_nonfinite_and_no_assumed_units():
    with freeze_time(NOW):
        assert state_number(State("sensor.p", "1.5", {"unit_of_measurement": "kW"}), NOW, "power") == 1500
        assert state_number(State("sensor.t", "68", {"unit_of_measurement": "°F"}), NOW, "temperature") == 20
        assert state_number(State("sensor.w", "36", {"unit_of_measurement": "km/h"}), NOW, "wind") == 10
        assert state_number(State("sensor.p", "1.5"), NOW, "power") is None
        assert state_number(State("sensor.p", "nan", {"unit_of_measurement": "W"}), NOW, "power") is None
    with freeze_time(NOW - timedelta(hours=1)):
        stale = State("sensor.p", "500", {"unit_of_measurement": "W"})
    assert state_number(stale, NOW, "power") is None


async def test_actual_ha_events_unknown_curtailment_and_attribute_updates(hass):
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": site().to_dict()})
    entry.add_to_hass(hass)
    client = AsyncMock()
    coordinator = AdaptiveSolarCoordinator(hass, entry, site(), client)
    with freeze_time(NOW):
        hass.states.async_set("binary_sensor.curtailed", "off")
        coordinator.async_start_tracking()
        hass.states.async_set("sensor.energy", "10", {"unit_of_measurement": "kWh"})
        await hass.async_block_till_done()
    with freeze_time(NOW + timedelta(minutes=5)):
        hass.states.async_set("sensor.energy", "10.1", {"unit_of_measurement": "kWh"})
        await hass.async_block_till_done()
    assert len(coordinator.intervals) == 1
    with freeze_time(NOW + timedelta(minutes=8)):
        hass.states.async_set("binary_sensor.curtailed", "unknown")
        await hass.async_block_till_done()
        hass.states.async_set("binary_sensor.curtailed", "off")
        await hass.async_block_till_done()
    with freeze_time(NOW + timedelta(minutes=10)):
        hass.states.async_set("sensor.energy", "10.2", {"unit_of_measurement": "kWh"})
        await hass.async_block_till_done()
    assert len(coordinator.intervals) == 1
    # Attribute-only updates cannot establish a new numeric measurement anchor.
    with freeze_time(NOW + timedelta(minutes=25)):
        hass.states.async_set("sensor.energy", "10.2", {"unit_of_measurement": "kWh", "other": True})
        await hass.async_block_till_done()
    with freeze_time(NOW + timedelta(minutes=29)):
        hass.states.async_set("sensor.energy", "10.3", {"unit_of_measurement": "kWh"})
        await hass.async_block_till_done()
    assert len(coordinator.intervals) == 1
    await coordinator.async_close()


async def test_restore_preserves_features_but_never_meter_anchor_and_config_change_clears(hass):
    config = site()
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    with freeze_time(NOW):
        first = AdaptiveSolarCoordinator(hass, entry, config, AsyncMock())
        await first.async_restore()
        first.archive = [archived()]
        first.async_commit_setup()
        await first.async_close()
        second = AdaptiveSolarCoordinator(hass, entry, config, AsyncMock())
        await second.async_restore()
        assert second.archive == first.archive
        assert second.tracker.anchors == {}
        changed = SiteConfig.from_dict({**config.to_dict(), "latitude": 53})
        third = AdaptiveSolarCoordinator(hass, entry, changed, AsyncMock())
        await third.async_restore()
        assert third.archive == []
        await second.async_close()
        await third.async_close()


async def test_executor_forecast_cold_start_and_prospective_archive(hass):
    config = site()
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    weather = WeatherForecast("best_match", NOW, tuple(WeatherPoint(NOW + timedelta(hours=hour), NOW + timedelta(hours=hour + 1), 500, 600, 100, 20, 2, 30) for hour in range(3)))
    client = AsyncMock()
    client.async_forecasts.return_value = (weather,)
    coordinator = AdaptiveSolarCoordinator(hass, entry, config, client)
    with freeze_time(NOW + timedelta(minutes=15)):
        result = await coordinator._async_update_data()
    assert result.points
    assert all(datetime.fromisoformat(row["start"]) >= result.issued_at for row in coordinator.archive)
    assert len(coordinator.archive) == 2
    assert coordinator.intervals == []
    assert result.power_at(NOW + timedelta(minutes=20), "i") is not None
    await coordinator.async_close()


async def test_archive_retains_representative_leads_within_each_bin(hass):
    config = site()
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    coordinator = AdaptiveSolarCoordinator(hass, entry, config, AsyncMock())
    point = ForecastPoint(NOW, NOW + timedelta(hours=1), "i", 2000, 2100, features={"baseline_w": 2000, "sun_elevation_deg": 45})
    for hours in (120, 100, 72, 30, 12, 4, 2):
        coordinator._archive_result(ForecastResult(NOW - timedelta(hours=hours), (point,)), available_at=NOW - timedelta(hours=hours))
    assert len(coordinator.archive) == 7
    assert {datetime.fromisoformat(row["issued_at"]) for row in coordinator.archive} == {NOW - timedelta(hours=hours) for hours in (120, 100, 72, 30, 12, 4, 2)}
    tracker = EnergyIntervalTracker()
    tracker.record("i", NOW, 10, True, 5000)
    measured = tracker.record("i", NOW + timedelta(minutes=5), 10.1, True, 5000)
    assert join_training(coordinator.archive, [measured]) == []
    measured = {**measured, "end": (NOW + timedelta(hours=1)).isoformat(), "observed_at": (NOW + timedelta(hours=1)).isoformat(), "energy_kwh": 1.2}
    samples = join_training(coordinator.archive, [measured])
    assert len(samples) == 7
    assert all(sample.actual_w == pytest.approx(1200) for sample in samples)
    await coordinator.async_close()


async def test_diagnostics_excludes_location_sensor_ids_and_history(hass):
    from custom_components.adaptive_solar.diagnostics import async_get_config_entry_diagnostics
    import json

    config = site()
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    client = AsyncMock()
    client.errors = {}
    entry.runtime_data = coordinator = AdaptiveSolarCoordinator(hass, entry, config, client)
    text = json.dumps(await async_get_config_entry_diagnostics(hass, entry))
    assert "latitude" not in text and "longitude" not in text
    assert "sensor.energy" not in text and "sensor.power" not in text
    assert "binary_sensor.curtailed" not in text
    await coordinator.async_close()


async def test_thousand_high_frequency_meter_ticks_are_one_exact_interval(hass):
    config = site()
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    coordinator = AdaptiveSolarCoordinator(hass, entry, config, AsyncMock())
    tracker = coordinator.tracker
    tracker.record("i", NOW, 10, True, 5000)
    for second in range(1, 1001):
        row = tracker.record("i", NOW + timedelta(seconds=second), 10 + second / 3600, True, 5000)
        coordinator._append_interval(row)
    assert len(coordinator.intervals) == 1
    assert join_training([archived()], coordinator.intervals) == []
    assert coordinator.intervals[0]["energy_kwh"] == pytest.approx(1000 / 3600)
    for second in range(1001, 3601):
        coordinator._append_interval(tracker.record("i", NOW + timedelta(seconds=second), 10 + second / 3600, True, 5000))
    sample = join_training([archived()], coordinator.intervals)[0]
    assert sample.actual_w == pytest.approx(1000)
    assert (sample.end - sample.start).total_seconds() == 3600
    # Missing whole-period evidence leaves a separate segment, never bridges it.
    tracker.invalidate("i")
    assert tracker.record("i", NOW + timedelta(seconds=3601), 10 + 3601 / 3600, True, 5000) is None
    coordinator._append_interval(tracker.record("i", NOW + timedelta(seconds=3602), 10 + 3602 / 3600, True, 5000))
    assert len(coordinator.intervals) == 2
    await coordinator.async_close()


async def test_complete_daily_snapshot_is_frozen_at_midnight_and_survives_reload(hass):
    from custom_components.adaptive_solar.sensor import day_bounds

    config = site()
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    coordinator = AdaptiveSolarCoordinator(hass, entry, config, AsyncMock())
    await coordinator.async_restore()
    start, end = day_bounds(NOW, config.timezone, 1)
    points = tuple(ForecastPoint(start + timedelta(hours=h), start + timedelta(hours=h + 1), "i", 1000, 1000) for h in range(24))
    coordinator._archive_result(ForecastResult(start - timedelta(hours=2), points), available_at=start - timedelta(hours=2))
    first = coordinator.daily_snapshots["2026-06-02"]
    assert first["energies"] == {"i": 24}
    coordinator._archive_result(ForecastResult(start - timedelta(minutes=5), points), available_at=start - timedelta(minutes=5))
    saved = dict(coordinator.daily_snapshots["2026-06-02"])
    revised = tuple(ForecastPoint(point.start, point.end, "i", 4000, 4000) for point in points)
    coordinator._archive_result(ForecastResult(start + timedelta(minutes=5), revised), available_at=start + timedelta(minutes=5))
    assert coordinator.daily_snapshots["2026-06-02"] == saved
    with freeze_time(start + timedelta(hours=1)):
        coordinator.async_commit_setup()
        await coordinator.async_close()
        restored = AdaptiveSolarCoordinator(hass, entry, config, AsyncMock())
        await restored.async_restore()
        assert restored.daily_snapshots["2026-06-02"] == saved
        await restored.async_close()
