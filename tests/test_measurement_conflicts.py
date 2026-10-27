"""Available conflicts at either target edge cannot become training labels."""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

from freezegun import freeze_time
import pytest

from custom_components.adaptive_solar.coordinator import join_training
from custom_components.adaptive_solar.core.measurement import MeasurementIndex, blocks
from tests.test_measurement_lineage import counter_series, forecast_cells, qualified
from tests.test_meter_quality import coordinator
from tests.test_training_alignment import NOW, archived, measured


def conflict_rows(edge, *, v2=False):
    start, end = ((-5, 5) if edge == "left" else (55, 65))
    rows = [measured(NOW + timedelta(minutes=1), NOW + timedelta(minutes=59)),
            measured(NOW + timedelta(minutes=start), NOW + timedelta(minutes=end), power=1500)]
    return [qualified(row) for row in rows] if v2 else rows


@pytest.mark.parametrize("edge", ["left", "right"])
@pytest.mark.parametrize("v2", [False, True])
def test_crossing_conflict_rejects_only_affected_target(edge, v2):
    independent = NOW + timedelta(hours=2)
    rows = [*conflict_rows(edge, v2=v2), measured(independent, independent + timedelta(hours=1))]
    diagnostics = {}
    samples = join_training([archived(), archived(start=independent)], rows, diagnostics=diagnostics)
    assert len(samples) == 1 and samples[0].start == independent
    assert diagnostics["i"]["accepted_target_cells"] == diagnostics["i"]["rejected_target_cells"] == 1
    assert diagnostics["i"]["rejection_reasons"] == {"overlapping_measurements": 1}


def test_prefix_max_detects_left_crossing_behind_many_short_earlier_rows():
    rows = [measured(NOW - timedelta(minutes=55), NOW + timedelta(minutes=3)),
            measured(NOW - timedelta(minutes=45), NOW - timedelta(minutes=40)),
            measured(NOW - timedelta(minutes=35), NOW - timedelta(minutes=30)),
            measured(NOW + timedelta(minutes=1), NOW + timedelta(minutes=59))]
    assert join_training([archived()], rows) == []


def test_touching_cross_boundary_neighbors_are_not_overlaps():
    rows = [measured(NOW - timedelta(minutes=5), NOW + timedelta(minutes=1)),
            measured(NOW + timedelta(minutes=1), NOW + timedelta(minutes=59)),
            measured(NOW + timedelta(minutes=59), NOW + timedelta(minutes=65))]
    sample = join_training([archived()], rows)[0]
    assert sample.start == NOW + timedelta(minutes=1) and sample.end == NOW + timedelta(minutes=59)
    assert sample.actual_w == pytest.approx(1000)


@pytest.mark.parametrize("edge", ["left", "right"])
@pytest.mark.parametrize("reverse", [False, True])
def test_future_crossing_conflict_does_not_contaminate_earlier_cutoff(edge, reverse):
    rows = conflict_rows(edge)
    received = NOW + timedelta(hours=2)
    rows[1]["observed_at"] = received.isoformat()
    rows = rows[::-1] if reverse else rows
    before = join_training([archived()], rows, as_of=received - timedelta(microseconds=1))
    assert len(before) == 1 and before[0].actual_w == pytest.approx(1000)
    assert join_training([archived()], rows, as_of=received) == []


def test_unfinalized_crossing_row_cannot_conflict_with_a_finalized_measurement():
    rows = conflict_rows("right")
    rows[1]["observed_at"] = (NOW + timedelta(minutes=54)).isoformat()
    assert len(join_training([archived()], rows, as_of=NOW + timedelta(hours=2))) == 1


@pytest.mark.parametrize("edge", ["left", "right"])
async def test_restored_individually_plausible_crossings_cannot_train_affected_hour(hass, edge):
    instance = coordinator(hass)
    independent = NOW + timedelta(hours=2)
    original = conflict_rows(edge, v2=True) + [measured(independent, independent + timedelta(hours=1))]
    archive = [archived(), archived(start=independent)]
    with freeze_time(NOW + timedelta(hours=4)):
        payload = {**instance._stored(), "intervals": original, "archive": archive}
        instance._store.async_load = AsyncMock(return_value=payload)
        await instance.async_restore()
        assert instance._store_writable
        assert instance.intervals == original  # Preserve unrelated valid history.
        diagnostics = {}
        samples = join_training(instance.archive, instance.intervals,
                                as_of=NOW + timedelta(hours=4), diagnostics=diagnostics)
    assert len(samples) == 1 and samples[0].start == independent
    assert diagnostics["i"]["rejection_reasons"] == {"overlapping_measurements": 1}
    await instance.async_close()


def test_local_conflict_does_not_disable_later_independent_endpoint_window():
    start = NOW + timedelta(hours=3, minutes=2)
    rows = conflict_rows("left", v2=True) + counter_series(start, [300] * 12)
    samples = join_training([archived(), *forecast_cells(NOW + timedelta(hours=3), count=2)], rows,
                            as_of=NOW + timedelta(hours=5))
    assert len(samples) == 1 and samples[0].start == start
    assert samples[0].features["measurement_endpoint_window"] == 1


def test_target_queries_visit_only_their_own_parts_after_one_index_build():
    rows = [measured(NOW + timedelta(minutes=index), NOW + timedelta(minutes=index + 1))
            for index in range(10000)]
    index = MeasurementIndex([(datetime.fromisoformat(row["start"]), datetime.fromisoformat(row["end"]), row)
                              for row in rows], as_of=None)
    class CountedRows:
        def __init__(self, values):
            self.values, self.reads = values, 0

        def __getitem__(self, position):
            self.reads += 1
            return self.values[position]
    counted = CountedRows(index.rows)
    index.rows = counted
    for target in range(1000):
        start = NOW + timedelta(minutes=target)
        selected, reasons = blocks(index, start, start + timedelta(hours=1))
        assert len(selected) == 1 and selected[0].duration == 3600 and reasons == set()
    assert counted.reads <= 1000 * 65  # Bound work by target support, not the10,000-row history.
