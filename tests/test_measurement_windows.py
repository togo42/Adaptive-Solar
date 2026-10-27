"""Synthetic counter bursts and intact target blocks; no physical accuracy claim."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta

from freezegun import freeze_time
import pytest

from custom_components.adaptive_solar.coordinator import EnergyIntervalTracker, join_training
from custom_components.adaptive_solar.core.learning import ResidualLearner
from tests.test_learning import EPOCH, synthetic_days
from tests.test_meter_quality import UNIT, coordinator
from tests.test_training_alignment import NOW, archived, measured


def test_small_counter_burst_waits_for_a_real_plausible_endpoint_without_losing_energy():
    tracker = EnergyIntervalTracker()
    tracker.record("i", NOW, 10, True, 5000)
    for ms, value in ((8, 10.0001), (16, 10.0002)):
        assert tracker.record("i", NOW + timedelta(milliseconds=ms), value, True, 5000) is None
    assert tracker.anchors["i"] == (NOW, 10)
    assert tracker.pending["i"][0] == NOW + timedelta(milliseconds=16)
    # Delayed/nonforward reports cannot revise the pending lineage either.
    assert tracker.record("i", NOW + timedelta(milliseconds=12), 9, True, 5000) is None
    receipt = NOW + timedelta(seconds=3)
    row = tracker.record("i", NOW + timedelta(seconds=2), 10.001, True, 5000, observed_at=receipt)
    assert {key: row[key] for key in ("inverter_id", "start", "end", "observed_at", "energy_kwh")} == {"inverter_id": "i", "start": NOW.isoformat(),
                   "end": (NOW + timedelta(seconds=2)).isoformat(),
                   "observed_at": receipt.isoformat(), "energy_kwh": pytest.approx(.001)}
    assert not tracker.pending
    assert tracker.events["i"]["deferred_power_check"] == 2
    assert tracker.events["i"]["accepted_deferred_delta"] == 1
    assert tracker.events["i"]["power_above_output_cap"] == 0


def test_coarse_energy_steps_use_the_whole_measured_span_without_clipping():
    tracker = EnergyIntervalTracker()
    tracker.record("i", NOW, 7000, True, 5400)
    assert tracker.record("i", NOW + timedelta(seconds=6), 7000.01025390625, True, 5400) is None
    row = tracker.record("i", NOW + timedelta(seconds=15), 7000.0205078125, True, 5400)
    assert row["start"] == NOW.isoformat()
    assert row["energy_kwh"] == .0205078125
    assert row["end"] == (NOW + timedelta(seconds=15)).isoformat()


@pytest.mark.parametrize("seconds,energy", [(0.008, 11), (60, 10.12), (901, 10.0001)])
def test_large_jumps_persistent_excess_and_missing_reports_still_reanchor_without_energy(seconds, energy):
    tracker = EnergyIntervalTracker()
    tracker.record("i", NOW, 10, True, 5000)
    if seconds > .008:
        assert tracker.record("i", NOW + timedelta(milliseconds=8), 10.0001, True, 5000) is None
    stamp = NOW + timedelta(seconds=seconds)
    assert tracker.record("i", stamp, energy, True, 5000) is None
    assert not tracker.pending
    assert tracker.anchors["i"] == (stamp, energy)
    row = tracker.record("i", stamp + timedelta(minutes=1), energy + .01, True, 5000)
    assert row["start"] == stamp.isoformat() and row["energy_kwh"] == pytest.approx(.01)


def test_pending_energy_can_complete_at_exactly_60_seconds():
    tracker = EnergyIntervalTracker()
    tracker.record("i", NOW, 10, True, 5000)
    tracker.record("i", NOW + timedelta(milliseconds=8), 10.0001, True, 5000)
    row = tracker.record("i", NOW + timedelta(seconds=60), 10.01, True, 5000)
    assert row["energy_kwh"] == pytest.approx(.01) and row["start"] == NOW.isoformat()


def test_reset_is_checked_against_the_latest_pending_report_not_only_the_anchor():
    tracker = EnergyIntervalTracker()
    tracker.record("i", NOW, 10, True, 5000)
    tracker.record("i", NOW + timedelta(milliseconds=8), 10.0001, True, 5000)
    reset = NOW + timedelta(milliseconds=16)
    assert tracker.record("i", reset, 10.00005, True, 5000) is None
    assert tracker.anchors["i"] == (reset, 10.00005) and not tracker.pending
    assert tracker.events["i"]["counter_reset"] == 1


@pytest.mark.parametrize("kind", ["invalidate", "invalid_counter", "curtailed"])
def test_pending_energy_never_bridges_invalid_measurements_or_curtailment(kind):
    tracker = EnergyIntervalTracker()
    tracker.record("i", NOW, 10, True, 5000)
    tracker.record("i", NOW + timedelta(milliseconds=8), 10.0001, True, 5000)
    if kind == "invalidate":
        tracker.invalidate("i", "measurement_invalidated")
    else:
        assert tracker.record("i", NOW + timedelta(seconds=1),
                              None if kind == "invalid_counter" else 10.0001,
                              kind != "curtailed", 5000) is None
    assert not tracker.pending
    at = NOW + timedelta(seconds=2)
    assert tracker.record("i", at, 10.0002, True, 5000) is None
    row = tracker.record("i", at + timedelta(seconds=2), 10.0004, True, 5000)
    assert row["start"] == at.isoformat() and row["energy_kwh"] == pytest.approx(.0002)


async def test_native_ha_counter_burst_is_coalesced_only_by_genuine_reports(hass):
    instance = coordinator(hass)
    with freeze_time(NOW):
        hass.states.async_set("binary_sensor.curtailed", "off")
        instance.async_start_tracking()
        hass.states.async_set("sensor.energy", "10", UNIT)
        await hass.async_block_till_done()
    with freeze_time(NOW + timedelta(milliseconds=8)):
        hass.states.async_set("sensor.energy", "10.0001", UNIT)
        await hass.async_block_till_done()
    assert not instance.intervals and "i" in instance.tracker.pending
    with freeze_time(NOW + timedelta(seconds=2)):
        # A forecast update is not a measurement report and cannot flush it.
        await instance._async_update_data()
        assert not instance.intervals
        hass.states.async_set("sensor.energy", "10.0004", UNIT)
        await hass.async_block_till_done()
    assert len(instance.intervals) == 1 and not instance.tracker.pending
    assert instance.intervals[0]["start"] == NOW.isoformat()
    assert instance.intervals[0]["end"] == (NOW + timedelta(seconds=2)).isoformat()
    assert instance.intervals[0]["energy_kwh"] == pytest.approx(.0004)
    await instance.async_close()


@pytest.mark.parametrize("signal", ["curtailment", "measurement_validity"])
async def test_native_control_burst_discards_pending_energy_before_recovery(hass, signal):
    from tests.test_measurement_validity import FLAG, config, coordinator as validity_coordinator

    if signal == "measurement_validity":
        instance, _ = validity_coordinator(hass, config())
        entity, valid, invalid = FLAG, "on", "off"
    else:
        instance = coordinator(hass)
        entity, valid, invalid = "binary_sensor.curtailed", "off", "on"
    with freeze_time(NOW):
        hass.states.async_set(entity, valid)
        instance.async_start_tracking()
    with freeze_time(NOW + timedelta(seconds=1)):
        hass.states.async_set("sensor.energy", "10", UNIT)
        await hass.async_block_till_done()
    with freeze_time(NOW + timedelta(seconds=1, milliseconds=8)):
        hass.states.async_set("sensor.energy", "10.0001", UNIT)
        await hass.async_block_till_done()
    assert "i" in instance.tracker.pending
    with freeze_time(NOW + timedelta(seconds=2)):
        hass.states.async_set(entity, invalid)
        hass.states.async_set(entity, valid)
        await hass.async_block_till_done()
    assert not instance.tracker.pending
    with freeze_time(NOW + timedelta(seconds=3)):
        hass.states.async_set("sensor.energy", "10.0003", UNIT)
        await hass.async_block_till_done()
    assert not instance.intervals
    with freeze_time(NOW + timedelta(seconds=4)):
        hass.states.async_set("sensor.energy", "10.0004", UNIT)
        await hass.async_block_till_done()
    assert len(instance.intervals) == 1
    assert instance.intervals[0]["start"] == (NOW + timedelta(seconds=3)).isoformat()
    assert instance.intervals[0]["energy_kwh"] == pytest.approx(.0001)
    await instance.async_close()


@pytest.mark.parametrize("reverse", [False, True])
def test_long_valid_later_block_survives_an_early_fragment_without_summing_across_the_gap(reverse):
    early = measured(NOW, NOW + timedelta(seconds=30), power=3000)
    later = measured(NOW + timedelta(minutes=1), NOW + timedelta(hours=1), power=500)
    intervals = [early, later]
    before = deepcopy(intervals)
    quality = {}
    samples = join_training([archived()], intervals[::-1] if reverse else intervals,
                            as_of=NOW + timedelta(hours=2), diagnostics=quality)
    assert len(samples) == 1
    row = samples[0]
    assert row.start == NOW + timedelta(minutes=1) and row.actual_w == pytest.approx(500)
    assert row.features["measurement_coverage_fraction"] == pytest.approx(59 / 60)
    assert row.features["measurement_edge_seconds"] == 60
    assert quality["i"]["rejected_target_cells"] == 0
    assert quality["i"]["rejection_reasons"] == {}
    assert intervals == before


@pytest.mark.parametrize("duration,left,right,accepted", [
    (1800, 72, 72, True), (1800, 73, 72, False),
    (3600, 144, 144, True), (3600, 145, 144, False),
    (3600, 180, 108, True), (3600, 180, 0, True), (3600, 181, 0, False),
    (3600, 180, 180, False), (10800, 180, 180, True), (10800, 181, 0, False),
])
def test_92_percent_coverage_and_absolute_three_minute_edges_are_joint_requirements(duration, left, right, accepted):
    end = NOW + timedelta(seconds=duration)
    rows = [measured(NOW + timedelta(seconds=left), end - timedelta(seconds=right))]
    samples = join_training([archived(duration=duration, lead=4)], rows)
    assert bool(samples) is accepted
    if accepted:
        assert samples[0].actual_w == pytest.approx(1000)
        assert samples[0].features["measurement_edge_seconds"] == max(left, right)
        assert samples[0].features["measurement_coverage_fraction"] >= .92


def test_middle_gap_is_not_filled_even_if_total_measured_duration_exceeds_92_percent():
    end = NOW + timedelta(hours=1)
    rows = [measured(NOW, NOW + timedelta(minutes=30)), measured(NOW + timedelta(minutes=30, seconds=1), end)]
    assert join_training([archived()], rows) == []


@pytest.mark.parametrize("start", ["2026-03-29T01:00:00+01:00", "2026-10-25T02:00:00+02:00",
                                   "2026-10-25T02:00:00+01:00"])
def test_absolute_measurement_windows_keep_their_utc_duration_through_both_dst_changes(start):
    from datetime import UTC, datetime

    a = datetime.fromisoformat(start).astimezone(UTC)
    b = a + timedelta(hours=1)
    sample = join_training([archived(start=a)], [measured(a + timedelta(seconds=144), b - timedelta(seconds=144))])[0]
    assert (sample.end - sample.start).total_seconds() == 3312
    assert sample.features["measurement_coverage_fraction"] == pytest.approx(.92)
    assert sample.actual_w == pytest.approx(1000)


def test_available_block_selection_ignores_later_receipts_before_overlap_and_duplicate_checks():
    end = NOW + timedelta(hours=1)
    known = measured(NOW + timedelta(minutes=1), end, power=500)
    future = {**measured(NOW, end, power=9000), "observed_at": (end + timedelta(minutes=5)).isoformat()}
    samples = join_training([archived()], [future, known], as_of=end + timedelta(minutes=1))
    assert len(samples) == 1 and samples[0].actual_w == pytest.approx(500)


def test_current_target_is_not_a_final_label_even_if_92_percent_is_already_measured():
    quality = {}
    end = NOW + timedelta(hours=1)
    known = measured(NOW, end - timedelta(minutes=3))
    assert join_training([archived()], [known], as_of=end - timedelta(minutes=2), diagnostics=quality) == []
    assert quality["i"]["pending_target_cells"] == 1
    assert quality["i"]["completed_target_cells"] == 0


def test_identical_measurement_duplicates_do_not_inflate_energy_and_conflicts_fail_closed():
    row = measured()
    samples = join_training([archived()], [row, row])
    assert len(samples) == 1 and samples[0].actual_w == pytest.approx(1000)
    assert join_training([archived()], [row, {**row, "energy_kwh": 2}]) == []
    assert join_training([archived()], [row, measured(NOW, NOW + timedelta(minutes=30))]) == []


@pytest.mark.parametrize("duration,left,right,accepted", [
    (1800, 72, 72, True), (1800, 73, 72, False), (3600, 180, 108, True),
    (3600, 181, 0, False), (10800, 180, 180, True), (10800, 181, 0, False),
])
def test_learner_independently_enforces_the_same_duration_and_edge_policy(duration, left, right, accepted):
    original = synthetic_days(count=1)[0]
    coverage = (duration - left - right) / duration
    row = replace(original, start=original.start + timedelta(seconds=left),
                  end=original.start + timedelta(seconds=duration - right),
                  observed_at=original.start + timedelta(seconds=duration),
                  features={**original.features, "target_duration_seconds": duration,
                            "measurement_coverage_fraction": coverage,
                            "measurement_edge_fraction": max(left, right) / duration})
    learner = ResidualLearner().fit([row], EPOCH + timedelta(days=50))
    assert learner.status[row.inverter_id]["rejected_rows"] == int(not accepted)
