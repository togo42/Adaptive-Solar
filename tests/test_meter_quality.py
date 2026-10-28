"""Whole counter deltas, fixed alignment gates and real HA report boundaries."""
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from freezegun import freeze_time
from homeassistant.core import Event, State
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_solar.coordinator import AdaptiveSolarCoordinator, join_training
from custom_components.adaptive_solar.core.models import InverterConfig, SiteConfig, StringConfig, WeatherForecast, WeatherPoint

NOW = datetime(2026, 6, 1, 10, tzinfo=UTC)
UNIT = {"unit_of_measurement": "kWh"}


def coordinator(hass, *, configured=True):
    config = SiteConfig(52, 13, "UTC", (StringConfig("s", "i", 5, 30, 180),),
                        (InverterConfig("i", 5, energy_entity_id="sensor.energy" if configured else None,
                                        curtailed_entity_id="binary_sensor.curtailed"),))
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    client = AsyncMock()
    client.async_forecasts.return_value = (WeatherForecast("best_match", NOW, (
        WeatherPoint(NOW + timedelta(hours=2), NOW + timedelta(hours=3), 500, 600, 100, 20, 2, 30),)),)
    return AdaptiveSolarCoordinator(hass, entry, config, client)


def archived(*, duration=3600, issue=NOW - timedelta(hours=2)):
    return {"issued_at": issue.isoformat(), "start": NOW.isoformat(),
            "end": (NOW + timedelta(seconds=duration)).isoformat(), "inverter_id": "i",
            "baseline_w": 2000, "features": {"baseline_w": 2000, "sun_elevation_deg": 45}}


def periodic_measurements(instance, cadence, phase, *, hours=3):
    for seconds in range(phase - cadence, hours * 3600 + cadence + 1, cadence):
        stamp = NOW + timedelta(seconds=seconds)
        state = State("sensor.energy", str(10 + seconds / 3600), UNIT,
                      last_updated=stamp, last_reported=stamp)
        instance._record_energy(instance.site.inverters[0], state, stamp)


@pytest.mark.parametrize("cadence,phase,accepted", [(60, 0, True), (60, 1, True), (60, 59, True),
    (90, 0, True), (90, 1, True), (90, 89, True), (300, 0, True), (300, 1, False),
    (300, 150, False), (900, 0, True), (900, 1, False), (900, 450, False)])
async def test_counter_cadence_is_not_a_promise_of_hourly_alignment(hass, cadence, phase, accepted):
    instance = coordinator(hass)
    hass.states.async_set("binary_sensor.curtailed", "off")
    periodic_measurements(instance, cadence, phase)
    diagnostics = {}
    samples = join_training([archived()], instance.intervals, diagnostics=diagnostics,
                            as_of=NOW + timedelta(hours=4))
    assert bool(samples) is accepted
    quality = diagnostics["i"]
    assert quality["completed_target_cells"] == 1
    assert quality["accepted_target_cells"] == int(accepted)
    if accepted:
        assert samples[0].actual_w == pytest.approx(1000)
        assert samples[0].features["measurement_coverage_fraction"] >= 0.92
        assert samples[0].features["measurement_edge_seconds"] <= 180
    else:
        assert quality["rejection_reasons"]["insufficient_measurement_coverage"] == 1
        assert quality["rejection_reasons"].get("measurement_edge_exceeded", 0) == int(max(phase, cadence - phase) > 180)
    await instance.async_close()


async def test_whole_crossing_preserves_energy_and_supports_only_a_containing_target(hass):
    instance = coordinator(hass)
    hass.states.async_set("binary_sensor.curtailed", "off")
    periodic_measurements(instance, 300, 60)
    crossing = next(row for row in instance.intervals if row["start"] == (NOW + timedelta(minutes=56)).isoformat())
    assert crossing["end"] == (NOW + timedelta(hours=1, minutes=1)).isoformat()
    assert crossing["energy_kwh"] == pytest.approx(5 / 60)
    assert join_training([archived()], instance.intervals) == []
    # Four missing minutes reject the original3h target, but the original
    # forecast still covers two disjoint whole endpoint windows without any
    # splitting of meter energy at a forecast-hour boundary.
    shifted = join_training([archived(duration=10800)], instance.intervals)
    assert len(shifted) == 2
    assert all(row.features["measurement_endpoint_window"] == 1 for row in shifted)
    sample = join_training([archived(duration=10860)], instance.intervals)[0]
    assert sample.start == NOW + timedelta(minutes=1)
    assert sample.end == NOW + timedelta(hours=3, minutes=1)
    assert sample.actual_w == pytest.approx(1000)
    assert sample.features["measurement_coverage_fraction"] == pytest.approx(180 / 181)
    # Retaining the crossing never spreads its energy into either UTC hour.
    assert crossing in instance.intervals
    await instance.async_close()


async def test_join_quality_deduplicates_origins_regimes_and_reports_pending_targets(hass):
    instance = coordinator(hass)
    hass.states.async_set("binary_sensor.curtailed", "off")
    periodic_measurements(instance, 300, 1)
    rows = [archived(issue=NOW - timedelta(minutes=minute)) for minute in range(1, 101)]
    rows += [{**row, "features": {**row["features"], "ghi_regime": 1,
                                "ghi_nowcast_gain": 1, "ghi_observation_age_seconds": 0}} for row in rows]
    future = {**archived(), "start": (NOW + timedelta(days=1)).isoformat(),
              "end": (NOW + timedelta(days=1, hours=1)).isoformat()}
    diagnostics = {}
    assert join_training(rows + [future], instance.intervals, diagnostics=diagnostics,
                         as_of=NOW + timedelta(hours=4)) == []
    quality = diagnostics["i"]
    assert quality["completed_target_cells"] == quality["rejected_target_cells"] == 1
    assert quality["pending_target_cells"] == 1
    assert quality["rejection_reasons"]["measurement_edge_exceeded"] == 1
    assert quality["accepted_unique_measured_seconds"] == 0
    # Accepted duplicate origins likewise cannot create extra measured hours.
    periodic = coordinator(hass)
    periodic_measurements(periodic, 60, 0)
    samples = join_training(rows, periodic.intervals, diagnostics=diagnostics)
    assert samples
    assert diagnostics["i"]["accepted_unique_measured_seconds"] == 3600
    assert diagnostics["i"]["accepted_unique_target_hours"] == 1
    await instance.async_close()
    await periodic.async_close()


async def test_real_unchanged_zero_reports_form_a_zero_hour_then_a_positive_delta(hass):
    instance = coordinator(hass)
    with freeze_time(NOW):
        hass.states.async_set("binary_sensor.curtailed", "off")
        instance.async_start_tracking()
        hass.states.async_set("sensor.energy", "0", UNIT)
        await hass.async_block_till_done()
    for minute in range(5, 61, 5):
        with freeze_time(NOW + timedelta(minutes=minute)):
            hass.states.async_set("sensor.energy", "0", UNIT)
            await hass.async_block_till_done()
    assert len(instance.intervals) == 1
    assert instance.intervals[0]["energy_kwh"] == 0
    assert join_training([archived()], instance.intervals)[0].actual_w == 0
    assert instance.tracker.events["i"]["accepted_zero_delta"] == 12
    with freeze_time(NOW + timedelta(minutes=65)):
        hass.states.async_set("sensor.energy", "0.1", UNIT)
        await hass.async_block_till_done()
    assert instance.intervals[-1]["start"] == (NOW + timedelta(hours=1)).isoformat()
    assert instance.intervals[-1]["energy_kwh"] == pytest.approx(0.1)
    await instance.async_close()


async def test_unreported_held_zero_is_not_polled_into_a_measurement(hass):
    instance = coordinator(hass)
    with freeze_time(NOW):
        hass.states.async_set("binary_sensor.curtailed", "off")
        instance.async_start_tracking()
        hass.states.async_set("sensor.energy", "0", UNIT)
        await hass.async_block_till_done()
    with freeze_time(NOW + timedelta(minutes=30)):
        await instance._async_update_data()
        assert instance.intervals == []
        assert instance.tracker.anchors["i"] == (NOW, 0)
        hass.states.async_set("sensor.energy", "0", UNIT)
        await hass.async_block_till_done()
    assert instance.intervals == []
    assert instance.tracker.events["i"]["measurement_gap"] == 1
    await instance.async_close()


async def test_report_event_timestamp_beats_a_later_mutated_state_and_duplicates(hass):
    instance = coordinator(hass)
    with freeze_time(NOW):
        hass.states.async_set("binary_sensor.curtailed", "off")
        instance.async_start_tracking()
        hass.states.async_set("sensor.energy", "0", UNIT)
        await hass.async_block_till_done()
    at = NOW + timedelta(minutes=5)
    with freeze_time(at):
        hass.states.async_set("sensor.energy", "0", UNIT, force_update=True)
        await hass.async_block_till_done()
        state = hass.states.get("sensor.energy")
        state.last_reported = at + timedelta(minutes=1)  # HA may mutate this.
        event = Event("state_reported", {"entity_id": "sensor.energy", "new_state": state,
            "last_reported": at, "old_last_reported": NOW}, time_fired_timestamp=at.timestamp())
        instance._async_state_reported(event)
    assert instance.tracker.anchors["i"][0] == at
    assert instance.tracker.events["i"]["nonforward_timestamp"] == 1
    at += timedelta(minutes=5)
    event = Event("state_reported", {"entity_id": "sensor.energy", "new_state": state,
        "last_reported": at, "old_last_reported": at - timedelta(minutes=5)}, time_fired_timestamp=at.timestamp())
    state.last_reported = at + timedelta(hours=1)
    instance._async_state_reported(event)
    assert instance.intervals[0]["end"] == at.isoformat()
    assert instance.tracker.anchors["i"] == (at, 0)
    await instance.async_close()


@pytest.mark.parametrize("bad_state,bad_attributes", [("unknown", UNIT), ("unavailable", UNIT),
    ("0", {**UNIT, "restored": True}), ("0", {"unit_of_measurement": "W"})])
async def test_bad_or_restored_counter_report_never_bridges_into_zero_labels(hass, bad_state, bad_attributes):
    instance = coordinator(hass)
    with freeze_time(NOW):
        hass.states.async_set("binary_sensor.curtailed", "off")
        instance.async_start_tracking()
        hass.states.async_set("sensor.energy", "0", UNIT)
        await hass.async_block_till_done()
    for minute, value, attributes in ((5, bad_state, bad_attributes), (10, "0", UNIT)):
        with freeze_time(NOW + timedelta(minutes=minute)):
            hass.states.async_set("sensor.energy", value, attributes)
            await hass.async_block_till_done()
    assert instance.intervals == []
    with freeze_time(NOW + timedelta(minutes=15)):
        hass.states.async_set("sensor.energy", "0", UNIT)
        await hass.async_block_till_done()
    assert all(datetime.fromisoformat(row["start"]) >= NOW + timedelta(minutes=10) for row in instance.intervals)
    await instance.async_close()


async def test_report_subscription_filters_foreign_entities_and_unsubscribes(hass):
    instance = coordinator(hass)
    with freeze_time(NOW):
        hass.states.async_set("binary_sensor.curtailed", "off")
        instance.async_start_tracking()
        hass.states.async_set("sensor.foreign", "0", UNIT)
        hass.states.async_set("sensor.foreign", "0", UNIT)
        await hass.async_block_till_done()
        assert instance.tracker.anchors == {}
        hass.states.async_set("sensor.energy", "0", UNIT)
        await hass.async_block_till_done()
    await instance.async_close()
    before = dict(instance.tracker.events["i"])
    with freeze_time(NOW + timedelta(minutes=5)):
        hass.states.async_set("sensor.energy", "0", UNIT)
        hass.states.async_set("sensor.energy", "1", UNIT)
        await hass.async_block_till_done()
    assert instance.tracker.events["i"] == before
    assert instance._unsub is instance._unsub_reports is None
    assert instance.intervals == []


async def test_curtailed_zero_reports_cannot_bridge_the_control_gap(hass):
    instance = coordinator(hass)
    with freeze_time(NOW):
        hass.states.async_set("binary_sensor.curtailed", "off")
        instance.async_start_tracking()
        hass.states.async_set("sensor.energy", "0", UNIT)
        await hass.async_block_till_done()
    for minute, curtailed in ((5, "on"), (10, "off"), (15, "off")):
        with freeze_time(NOW + timedelta(minutes=minute)):
            hass.states.async_set("binary_sensor.curtailed", curtailed)
            await hass.async_block_till_done()
            hass.states.async_set("sensor.energy", "0", UNIT)
            await hass.async_block_till_done()
    assert len(instance.intervals) == 1
    assert instance.intervals[0]["start"] == (NOW + timedelta(minutes=10)).isoformat()
    assert instance.intervals[0]["end"] == (NOW + timedelta(minutes=15)).isoformat()
    assert instance.intervals[0]["energy_kwh"] == 0
    assert instance.tracker.events["i"]["blocked_curtailment"] == 1
    await instance.async_close()


async def test_restored_initial_zero_does_not_anchor_until_a_real_valid_report(hass):
    instance = coordinator(hass)
    with freeze_time(NOW):
        hass.states.async_set("binary_sensor.curtailed", "off")
        hass.states.async_set("sensor.energy", "0", {**UNIT, "restored": True})
        instance.async_start_tracking()
    for minute, attributes in ((5, {**UNIT, "restored": True}), (10, UNIT), (15, UNIT)):
        with freeze_time(NOW + timedelta(minutes=minute)):
            hass.states.async_set("sensor.energy", "0", attributes)
            await hass.async_block_till_done()
        assert instance.intervals == []
    assert instance.tracker.anchors["i"] == (NOW + timedelta(minutes=15), 0)
    await instance.async_close()


@pytest.mark.parametrize("configured", [False, True])
async def test_learning_status_explains_missing_source_and_alignment(hass, configured):
    instance = coordinator(hass, configured=configured)
    instance.archive = [archived()]
    with freeze_time(NOW + timedelta(hours=1)):
        await instance._async_update_data()
    quality = instance.learner_status["i"]["training_quality"]
    assert instance.learner_status["i"]["state"] == "insufficient_history"
    assert quality["alignment"]["completed_target_cells"] == 1
    assert quality["alignment"]["accepted_target_cells"] == 0
    assert quality["alignment"]["rejection_reasons"] == {"no_whole_measurement_inside_target": 1}
    assert ("invalid_or_unavailable_energy_source" if configured else "missing_energy_source") in quality["blocking_reasons"]
    assert quality["policy"]["min_coverage_fraction"] == 0.92
    assert quality["policy"]["max_missing_edge_seconds"] == 180
    assert quality["policy"]["counter_plausibility_window_seconds"] == 60
    assert quality["meter"]["report_evidence"] == "ha_receipt_not_physical_source_qualification"
    await instance.async_close()
