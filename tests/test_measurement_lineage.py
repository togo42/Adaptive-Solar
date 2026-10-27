"""Real endpoint support under slow/irregular counters; no accuracy claim."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from freezegun import freeze_time
import numpy as np
import pytest

from custom_components.adaptive_solar.const import MEASUREMENT_CONTRACT
from custom_components.adaptive_solar.coordinator import EnergyIntervalTracker, join_training
from custom_components.adaptive_solar.core.learning import _aligned_duration, _target_hours, _weights
from tests.test_meter_quality import coordinator
from tests.test_training_alignment import NOW, archived, measured


def forecast_cells(start=NOW, count=4, issues=(2,)):
    result = []
    for index in range(count):
        for lead in issues:
            row = archived(start=start + timedelta(hours=index))
            row["issued_at"] = (start - timedelta(hours=lead)).isoformat()
            row["baseline_w"] = 2000 + 1000 * index
            row["features"]["baseline_w"] = row["baseline_w"]
            result.append(row)
    return result


def counter_series(start, seconds):
    tracker = EnergyIntervalTracker()
    rows, elapsed = [], 0
    tracker.record("i", start, 10, True, 5000)
    for seconds_step in seconds:
        elapsed += seconds_step
        row = tracker.record("i", start + timedelta(seconds=elapsed), 10 + elapsed / 3600, True, 5000)
        assert row is not None
        rows.append(row)
    return rows


@pytest.mark.parametrize("cadence", [60, 300, 600])
@pytest.mark.parametrize("irregular", [False, True])
def test_slow_counter_hour_offset_uses_whole_real_deltas_and_original_forecast(cadence, irregular):
    start = NOW + timedelta(minutes=2)
    steps = [cadence] * (7200 // cadence)
    if irregular:
        # Timestamp-only variation conserves total duration and energy.
        steps = [value + (-7 if index % 2 == 0 else 7) for index, value in enumerate(steps)]
    rows = counter_series(start, steps)
    samples = join_training(forecast_cells(), rows)
    assert samples
    assert all(row.actual_w == pytest.approx(1000) and _aligned_duration(row) for row in samples)
    assert sum(_weights(samples)) <= 7200
    assert _target_hours(samples) <= 2
    if cadence in (300, 600):
        # Hourly rejection must not erase a continuous 10:02-11:02 counter.
        endpoint = [row for row in samples if row.features.get("measurement_endpoint_window")]
        assert len(endpoint) == 2
        assert endpoint[0].start == start
        assert endpoint[0].end >= start + timedelta(hours=1)
        assert endpoint[0].baseline_w == pytest.approx(
            (2000 * (3600 - 120) + 3000 * (endpoint[0].end - NOW - timedelta(hours=1)).total_seconds())
            / (endpoint[0].end - start).total_seconds())
        assert sum(row.actual_w * sum((b - a).total_seconds() for a, b in row.measurement_support)
                   / 3600000 for row in endpoint) == pytest.approx(2)


def qualified(row, lineage="a" * 32):
    return {**row, "measurement_contract": MEASUREMENT_CONTRACT, "continuity_id": lineage,
            "boundary_reason": None}


def test_ten_millisecond_gap_is_bounded_metadata_not_energy_or_measured_time():
    middle = NOW + timedelta(minutes=30)
    parts = [qualified(measured(NOW, middle)),
             qualified(measured(middle + timedelta(milliseconds=10), NOW + timedelta(hours=1)))]
    sample = join_training([archived()], parts)[0]
    assert sample.features["measurement_gap_seconds"] == pytest.approx(.01)
    assert sample.features["measurement_coverage_fraction"] == pytest.approx(3599.99 / 3600)
    assert sum(_weights([sample])) == pytest.approx(3599.99)
    assert _target_hours([sample]) == 0
    assert sample.actual_w == pytest.approx(1000)
    assert sample.actual_w * 3599.99 / 3600000 == pytest.approx(sum(row["energy_kwh"] for row in parts))
    assert _aligned_duration(sample)
    assert not _aligned_duration(replace(sample, features={**sample.features, "measurement_gap_seconds": 0}))


@pytest.mark.parametrize("kind", ["legacy", "reset", "invalid", "curtailment", "restart", "too_large"])
def test_minigaps_require_compatible_provenance_without_interruption(kind):
    middle = NOW + timedelta(minutes=30)
    a = qualified(measured(NOW, middle))
    b = qualified(measured(middle + timedelta(milliseconds=10), NOW + timedelta(hours=1)))
    if kind == "legacy":
        a = measured(NOW, middle)
        b = measured(middle + timedelta(milliseconds=10), NOW + timedelta(hours=1))
    elif kind == "too_large":
        b = qualified(measured(middle + timedelta(seconds=1.001), NOW + timedelta(hours=1)))
    else:
        b["continuity_id"], b["boundary_reason"] = "b" * 32, kind
    assert join_training([archived()], [a, b]) == []


def test_thousands_of_tiny_gaps_cannot_evade_the_per_hour_total_budget():
    # 1199 gaps of 10 ms would fit the legacy92% threshold; the5s budget
    # rejects the resulting hour instead of silently adding11.99 seconds.
    parts = [qualified(measured(NOW + timedelta(seconds=index * 3),
                                NOW + timedelta(seconds=(index + 1) * 3 - .01)))
             for index in range(1200)]
    assert join_training([archived()], parts) == []


@pytest.mark.parametrize("kind", ["sum", "gap", "receipt", "cap", "bool"])
def test_original_parts_cannot_invent_energy_endpoints_or_earlier_availability(kind):
    from custom_components.adaptive_solar.core.measurement import expand_interval

    end = NOW + timedelta(minutes=1)
    middle = NOW + timedelta(seconds=30)
    row = qualified(measured(NOW, end))
    row["measurement_parts"] = [[NOW.isoformat(), middle.isoformat(), middle.isoformat(), 1 / 120],
                                [middle.isoformat(), end.isoformat(), end.isoformat(), 1 / 120]]
    if kind == "sum":
        row["energy_kwh"] += .01
    elif kind == "gap":
        row["measurement_parts"][1][0] = (middle + timedelta(milliseconds=1)).isoformat()
    elif kind == "receipt":
        row["measurement_parts"][1][2] = middle.isoformat()
    elif kind == "cap":
        row["measurement_parts"][1][3] = 10
        row["energy_kwh"] = 10 + 1 / 120
    else:
        row["measurement_parts"][1][3] = True
    with pytest.raises(ValueError):
        expand_interval(row, cap_w=5000)


@pytest.mark.parametrize("seconds", [60.001, 300, 600, 900])
def test_pending_small_burst_waits_for_next_real_slow_counter_report(seconds):
    tracker = EnergyIntervalTracker()
    tracker.record("i", NOW, 10, True, 5000)
    assert tracker.record("i", NOW + timedelta(milliseconds=10), 10.0001, True, 5000) is None
    row = tracker.record("i", NOW + timedelta(seconds=seconds), 10.001, True, 5000)
    assert row["start"] == NOW.isoformat()
    assert row["energy_kwh"] == pytest.approx(.001)
    assert tracker.events["i"]["accepted_deferred_delta"] == 1


def test_pending_window_does_not_increase_the_allowed_initial_energy_jump():
    tracker = EnergyIntervalTracker()
    tracker.record("i", NOW, 10, True, 5000)
    assert tracker.record("i", NOW + timedelta(milliseconds=10), 10.2, True, 5000) is None
    assert not tracker.pending  # Larger than the original60-second quantum.
    assert tracker.events["i"]["power_above_output_cap"] == 1


def test_pending_timeout_preserves_its_specific_reason_and_starts_a_new_phase():
    tracker = EnergyIntervalTracker()
    tracker.record("i", NOW, 10, True, 5000)
    tracker.record("i", NOW + timedelta(milliseconds=10), 10.0001, True, 5000)
    assert tracker.record("i", NOW + timedelta(seconds=900.001), 10.001, True, 5000) is None
    assert tracker.events["i"]["counter_aggregation_timeout"] == 1
    assert not tracker.pending
    row = tracker.record("i", NOW + timedelta(seconds=960), 10.002, True, 5000)
    assert row["boundary_reason"] == "counter_aggregation_timeout"


@pytest.mark.parametrize("kind", ["reset", "invalid", "curtailed", "restart"])
def test_tracker_lineage_changes_after_real_interruptions(kind):
    tracker = EnergyIntervalTracker()
    tracker.record("i", NOW, 10, True, 5000)
    first = tracker.record("i", NOW + timedelta(minutes=1), 10.01, True, 5000)
    if kind == "restart":
        tracker = EnergyIntervalTracker()
        value = 10.02
        tracker.record("i", NOW + timedelta(minutes=2), value, True, 5000)
    elif kind == "reset":
        value = 0.01
        tracker.record("i", NOW + timedelta(minutes=2), value, True, 5000)
    else:
        tracker.record("i", NOW + timedelta(minutes=2), None if kind == "invalid" else 10.02,
                       kind != "curtailed", 5000)
        value = 10.03
        tracker.record("i", NOW + timedelta(minutes=3), value, True, 5000)
    last = tracker.record("i", NOW + timedelta(minutes=4), value + .01, True, 5000)
    assert last["continuity_id"] != first["continuity_id"]
    assert last["boundary_reason"]


@pytest.mark.parametrize("start_text", ["2026-03-29T01:02:00+01:00", "2026-10-25T02:02:00+02:00",
                                        "2026-10-25T02:02:00+01:00"])
def test_shifted_endpoint_windows_keep_real_duration_at_both_dst_transitions(start_text):
    start = datetime.fromisoformat(start_text).astimezone(UTC)
    cells = forecast_cells(start.replace(minute=0), count=2)
    sample = join_training(cells, counter_series(start, [300] * 12))[0]
    assert sample.start == start and sample.end == start + timedelta(hours=1)
    assert _target_hours([sample]) == 1
    assert sample.actual_w == pytest.approx(1000)


def test_endpoint_windows_apply_observation_availability_and_common_issue_gates():
    start = NOW + timedelta(minutes=2)
    rows = counter_series(start, [300] * 12)
    end = start + timedelta(hours=1)
    receipt = end + timedelta(minutes=10)
    rows[-1]["observed_at"] = receipt.isoformat()
    cells = forecast_cells(count=2)
    assert join_training(cells, rows, as_of=receipt - timedelta(microseconds=1)) == []
    assert join_training(cells, rows, as_of=receipt)[0].observed_at == receipt
    # Adjacent snapshots with different actual issues cannot silently become
    # a forecast that was never issued.
    cells[-1]["issued_at"] = (NOW - timedelta(hours=3)).isoformat()
    assert join_training(cells, rows, as_of=receipt) == []


@pytest.mark.parametrize("kind", ["regime", "partial", "late_issue", "stale_shade", "forecast_gap"])
def test_endpoint_integrals_do_not_bypass_forecast_compatibility(kind):
    start = NOW + timedelta(minutes=2)
    rows = counter_series(start, [300] * 12)
    cells = forecast_cells(count=2)
    if kind == "regime":
        cells[-1]["features"].update(ghi_regime=1, ghi_nowcast_gain=1.1, ghi_observation_age_seconds=1)
    elif kind == "partial":
        cells[-1]["features"]["source_partial_at_issue"] = 1
    elif kind == "late_issue":
        for cell in cells:
            cell["issued_at"] = (NOW + timedelta(minutes=1)).isoformat()
    elif kind == "stale_shade":
        cells[-1]["features"]["beam_shade_factor"] = float("nan")
    else:
        cells[-1]["start"] = (NOW + timedelta(hours=1, minutes=1)).isoformat()
    assert join_training(cells, rows) == []


def test_multiple_issues_do_not_multiply_measured_support_or_overlap_old_windows():
    rows = counter_series(NOW + timedelta(minutes=2), [300] * 24)
    samples = join_training(forecast_cells(issues=(2, 4)), rows)
    assert len(samples) == 4 and _target_hours(samples) == 2
    assert np.sum(_weights(samples)) == pytest.approx(7200)
    overlap = replace(samples[0], start=samples[0].start + timedelta(minutes=30),
                      measurement_support=((samples[0].start + timedelta(minutes=30), samples[0].end),))
    assert np.sum(_weights([samples[0], overlap])) == pytest.approx(3600)


def test_sixty_thousand_origins_share_one_hour_without_manufacturing_duration():
    sample = join_training([archived()], [qualified(measured())])[0]
    origins = [sample] * 60000
    assert _target_hours(origins) == 1
    weights = _weights(origins)
    assert len(weights) == 60000
    assert np.sum(weights) == pytest.approx(3600)


async def test_live_coalescing_and_restore_preserve_endpoint_energy_and_provenance(hass):
    from unittest.mock import AsyncMock

    instance = coordinator(hass)
    start = NOW + timedelta(minutes=2)
    rows = counter_series(start, [300] * 24)
    for row in rows:
        instance._append_interval(row)
    before = sum(row["energy_kwh"] for row in instance.intervals)
    instance.archive = forecast_cells()
    samples = join_training(instance.archive, instance.intervals)
    assert len(samples) == 2 and _target_hours(samples) == 2
    with freeze_time(start + timedelta(hours=3)):
        stored = instance._stored()
        restored = coordinator(hass)
        restored._store.async_load = AsyncMock(return_value=stored)
        await restored.async_restore()
    assert restored.intervals == instance.intervals
    assert sum(row["energy_kwh"] for row in restored.intervals) == pytest.approx(before)
    assert join_training(restored.archive, restored.intervals) == samples
    assert restored.tracker.anchors == {} and restored.tracker.lineage == {}
    await restored.async_close()
    await instance.async_close()


async def test_live_coalescing_preserves_irregular_original_endpoints_after_restart(hass):
    from unittest.mock import AsyncMock

    instance = coordinator(hass)
    start = NOW + timedelta(minutes=7)
    rows = counter_series(start, [300] * 10 + [180] + [300] * 6)
    cells = forecast_cells(count=2)
    cutoff = NOW + timedelta(hours=1, minutes=30)
    expected = join_training(cells, rows, as_of=cutoff)
    assert len(expected) == 1
    assert expected[0].start == start and expected[0].end == NOW + timedelta(hours=1, minutes=10)
    for row in rows:
        instance._append_interval(row)
    instance.archive = cells
    assert join_training(cells, instance.intervals, as_of=cutoff) == expected
    with freeze_time(cutoff):
        stored = instance._stored()
        restored = coordinator(hass)
        restored._store.async_load = AsyncMock(return_value=stored)
        await restored.async_restore()
    assert join_training(restored.archive, restored.intervals, as_of=cutoff) == expected
    assert sum(row["energy_kwh"] for row in instance.intervals) == pytest.approx(sum(row["energy_kwh"] for row in rows))
    await instance.async_close()
    await restored.async_close()


async def test_five_minute_reports_for_four_stages_retain_120_days_with_true_endpoints(hass):
    from custom_components.adaptive_solar.const import MAX_MEASUREMENT_PARTS, MAX_TRAINING_ROWS

    instance = coordinator(hass)
    start = NOW + timedelta(minutes=2)
    rows = counter_series(start, [300] * (120 * 24 * 12))
    for row in rows:
        for index in range(4):
            instance._append_interval({**row, "inverter_id": f"stage{index}"})
    with freeze_time(start + timedelta(days=120)):
        instance._prune(start + timedelta(days=120))
    assert len(instance.intervals) <= 120 * 24 * 4 * 2 < MAX_TRAINING_ROWS
    assert instance._measurement_part_count == 120 * 24 * 12 * 4 < MAX_MEASUREMENT_PARTS
    # Real measured support exceeds the unchanged28days/240h eligibility floor.
    assert min(datetime.fromisoformat(row["start"]) for row in instance.intervals) == start
    assert sum(row["energy_kwh"] for row in instance.intervals) == pytest.approx(120 * 24 * 4)
    await instance.async_close()


async def test_one_second_reports_compact_whole_deltas_and_keep_more_than_28_days(hass):
    from custom_components.adaptive_solar.const import MAX_MEASUREMENT_PARTS

    instance = coordinator(hass)
    rows = counter_series(NOW, [1] * 3600)
    for row in rows:
        instance._append_interval(row)
    assert len(instance.intervals) == 1
    template = instance.intervals[0]
    assert len(template["measurement_parts"]) == instance._measurement_part_count == 60
    assert template["energy_kwh"] == pytest.approx(sum(row["energy_kwh"] for row in rows))
    assert template["energy_kwh"] == pytest.approx(1)
    assert all((datetime.fromisoformat(part[1]) - datetime.fromisoformat(part[0])).total_seconds() == 60
               for part in template["measurement_parts"])
    assert join_training(forecast_cells(count=1), instance.intervals)[0].actual_w == pytest.approx(1000)
    # Replay the actual compacted support shape, preserving whole minute
    # energy and real report endpoints, over four independent stage histories.
    histories = []
    for hour in range(40 * 24):
        offset = timedelta(hours=hour)
        def shifted(stamp):
            return (datetime.fromisoformat(stamp) + offset).isoformat()
        for stage in range(4):
            histories.append({**template, "inverter_id": f"stage{stage}", "start": shifted(template["start"]),
                "end": shifted(template["end"]), "observed_at": shifted(template["observed_at"]),
                "measurement_parts": tuple((shifted(a), shifted(b), shifted(receipt), energy)
                                           for a, b, receipt, energy in template["measurement_parts"])})
    instance.intervals = histories
    instance._prune(NOW + timedelta(days=40))
    assert instance._measurement_part_count <= MAX_MEASUREMENT_PARTS
    for stage in range(4):
        retained = [row for row in instance.intervals if row["inverter_id"] == f"stage{stage}"]
        assert len(retained) >= 28 * 24
        assert len({datetime.fromisoformat(row["start"]).date() for row in retained}) >= 28
        assert sum(row["energy_kwh"] for row in retained) == pytest.approx(len(retained))
    await instance.async_close()


@pytest.mark.parametrize("bad", [42, "invalid", {"measurement_parts": 42}, {"measurement_parts": True},
                                {"measurement_parts": None}, {"measurement_parts": []}])
async def test_malformed_original_measurement_parts_preserve_store_and_allow_physics(hass, bad):
    from unittest.mock import AsyncMock

    instance = coordinator(hass)
    with freeze_time(NOW):
        stored = instance._stored()
        stored["intervals"] = [bad]
        instance._store.async_load = AsyncMock(return_value=stored)
        instance._store.async_save = AsyncMock()
        await instance.async_restore()
        assert not instance._store_writable and instance.intervals == []
        result = await instance._async_update_data()
        assert result.points and all(point.power_w == point.baseline_w for point in result.points)
        instance.async_commit_setup()
        assert not instance._persistence_active
        await instance.async_close()
    instance._store.async_save.assert_not_called()
