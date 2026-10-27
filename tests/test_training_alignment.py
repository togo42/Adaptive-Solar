"""External-review regressions: aligned target means, lead support and storage."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from freezegun import freeze_time
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_solar.coordinator import AdaptiveSolarCoordinator, LEARNING_FEATURE_CONTRACT, join_training, lead_bucket
from custom_components.adaptive_solar.core.learning import ResidualLearner, _target_hours, lead_bin
from custom_components.adaptive_solar.core.models import InverterConfig, SiteConfig, StringConfig, midpoint_lead_hours
from tests.test_learning import EPOCH, synthetic_days

NOW = datetime(2026, 6, 1, 10, tzinfo=UTC)


def archived(start=NOW, duration=3600, lead=1):
    end = start + timedelta(seconds=duration)
    issued = start + (end - start) / 2 - timedelta(hours=lead)
    return {"issued_at": issued.isoformat(), "start": start.isoformat(), "end": end.isoformat(), "inverter_id": "i", "baseline_w": 2000, "features": {"baseline_w": 2000, "lead_hours": lead}}


def measured(start=NOW, end=NOW + timedelta(hours=1), power=1000):
    return {"start": start.isoformat(), "end": end.isoformat(), "observed_at": end.isoformat(), "inverter_id": "i", "energy_kwh": power * (end - start).total_seconds() / 3600000}


@pytest.mark.parametrize("duration,edge", [(3600, 144), (1800, 72), (10800, 180)])
def test_fixed_coverage_and_edge_limits_align_hour_half_hour_and_three_hour_means(duration, edge):
    end = NOW + timedelta(seconds=duration)
    row = archived(duration=duration, lead=4)
    sample = join_training([row], [measured(NOW + timedelta(seconds=edge), end - timedelta(seconds=edge))])[0]
    assert sample.actual_w == pytest.approx(1000)
    assert sample.features["measurement_coverage_fraction"] == pytest.approx((duration - 2 * edge) / duration)
    assert sample.features["measurement_edge_fraction"] == pytest.approx(edge / duration)
    assert sample.features["measurement_edge_seconds"] == edge
    assert sample.features["lead_hours"] == row["features"]["lead_hours"]
    assert join_training([row], [measured(NOW + timedelta(seconds=edge + 1), end - timedelta(seconds=edge))]) == []


def test_internal_gap_and_biased_partial_interval_never_invent_boundary_energy():
    row = archived()
    assert join_training([row], [measured(NOW, NOW + timedelta(minutes=30)), measured(NOW + timedelta(minutes=31), NOW + timedelta(hours=1))]) == []
    assert join_training([row], [measured(NOW, NOW + timedelta(minutes=57))])
    assert join_training([row], [measured(NOW, NOW + timedelta(minutes=56, seconds=59))]) == []
    assert join_training([row], [measured(NOW + timedelta(minutes=1), NOW + timedelta(minutes=59))])
    assert join_training([row], [measured(NOW + timedelta(minutes=55), NOW + timedelta(hours=1))]) == []


def test_exactly_contiguous_measured_parts_can_form_one_cell_without_interpolation():
    parts = [measured(NOW + timedelta(minutes=minute), NOW + timedelta(minutes=minute + 5), power=1000 + minute * 10) for minute in range(0, 60, 5)]
    samples = join_training([archived()], parts)
    assert len(samples) == 1
    assert samples[0].actual_w == pytest.approx(sum(1000 + minute * 10 for minute in range(0, 60, 5)) / 12)
    assert sum(part["energy_kwh"] for part in parts) == pytest.approx(samples[0].actual_w / 1000)


@pytest.mark.parametrize("offset,accepted", [(-1, False), (0, True), (1, True)])
def test_join_enforces_label_receipt_at_exact_as_of_boundary(offset, accepted):
    observed = NOW + timedelta(hours=1, minutes=5)
    interval = {**measured(), "observed_at": observed.isoformat()}
    quality = {}
    samples = join_training([archived()], [interval], as_of=observed + timedelta(microseconds=offset), diagnostics=quality)
    assert len(samples) == int(accepted)
    if accepted:
        assert samples[0].observed_at == observed
        assert samples[0].actual_w == 1000
    report = quality["i"]
    assert report["count_scope"] == "unique_target_cells_not_forecast_origins"
    assert report["completed_target_cells"] == 1 and report["pending_target_cells"] == 0
    assert report["accepted_target_cells"] == int(accepted)
    assert report["rejected_target_cells"] == int(not accepted)
    assert report["rejection_reasons"] == ({} if accepted else {"observation_not_yet_available": 1})
    assert report["accepted_unique_measured_seconds"] == (3600 if accepted else 0)
    assert report["accepted_unique_target_hours"] == int(accepted)
    assert report["stored_unique_measured_seconds"] == 3600  # Stored does not mean known at the cutoff.


@pytest.mark.parametrize("reverse", [False, True])
def test_delayed_duplicate_origins_do_not_hide_available_targets_or_inflate_later_support(reverse):
    observed = NOW + timedelta(hours=1, minutes=10)
    prior = archived(start=NOW - timedelta(hours=1))
    origins = [archived(lead=1), archived(lead=4)]
    archive = [origins[0], origins[0], prior, origins[1], origins[1]]
    intervals = [measured(NOW - timedelta(hours=1), NOW), {**measured(), "observed_at": observed.isoformat()}]
    quality = {}
    samples = join_training(archive[::-1] if reverse else archive, intervals,
                            as_of=NOW + timedelta(minutes=30), diagnostics=quality)
    assert len(samples) == 1 and samples[0].end == NOW
    assert quality["i"]["completed_target_cells"] == quality["i"]["pending_target_cells"] == 1
    assert quality["i"]["accepted_target_cells"] == 1 and quality["i"]["rejected_target_cells"] == 0
    assert quality["i"]["rejection_reasons"] == {}  # Pending targets are not completed rejections.
    samples = join_training(archive[::-1] if reverse else archive, intervals,
                            as_of=observed - timedelta(minutes=1), diagnostics=quality)
    assert len(samples) == 1 and samples[0].end == NOW
    assert quality["i"]["accepted_target_cells"] == quality["i"]["rejected_target_cells"] == 1
    assert quality["i"]["rejection_reasons"] == {"observation_not_yet_available": 1}
    assert quality["i"]["accepted_unique_measured_seconds"] == 3600
    samples = join_training(archive[::-1] if reverse else archive, intervals, as_of=observed, diagnostics=quality)
    assert len(samples) == 3  # Two genuine issue origins, one duplicate each, plus the earlier target.
    assert len({(sample.start, sample.end, sample.issued_at) for sample in samples}) == 3
    assert all(sample.observed_at <= observed for sample in samples)
    assert quality["i"]["completed_target_cells"] == quality["i"]["accepted_target_cells"] == 2
    assert quality["i"]["rejected_target_cells"] == 0 and quality["i"]["rejection_reasons"] == {}
    assert quality["i"]["accepted_unique_measured_seconds"] == 7200
    assert quality["i"]["accepted_unique_target_hours"] == 2


def test_join_without_cutoff_retains_finalized_delayed_labels():
    observed = NOW + timedelta(days=1)
    samples = join_training([archived()], [{**measured(), "observed_at": observed.isoformat()}])
    assert len(samples) == 1 and samples[0].observed_at == observed


def test_tiny_segments_from_many_days_cannot_activate_or_count_as_target_hours():
    rows = [replace(row, end=row.start + timedelta(minutes=5)) for row in synthetic_days()]
    learner = ResidualLearner().fit(rows, EPOCH + timedelta(days=50))
    assert learner.status["wr"]["state"] == "insufficient_history"
    assert learner.status["wr"]["unique_target_hours"] == 0
    assert learner.status["wr"]["rejected_rows"] == len(rows)


def test_target_hours_are_unique_duration_not_counted_twice_by_origins_or_overlaps():
    row = synthetic_days(count=1)[0]
    halves = [replace(row, end=row.start + timedelta(minutes=30)), replace(row, start=row.start + timedelta(minutes=30))]
    assert _target_hours(halves * 10) == 1
    assert _target_hours([halves[0]] * 100) == 0


@pytest.mark.parametrize("boundary", [6, 24, 48, 96])
def test_archive_and_learner_share_exact_midpoint_bin_boundaries(boundary):
    start, end = NOW, NOW + timedelta(hours=1)
    for offset in (-0.001, 0, 0.001):
        issue = start + timedelta(minutes=30) - timedelta(hours=boundary + offset)
        assert midpoint_lead_hours(issue, start, end) == pytest.approx(boundary + offset)
        assert lead_bucket(issue, start, end) == lead_bin(boundary + offset)
    # Start lead is still 5.5h, but mean lead is exactly 6h: higher bin.
    issue = start - timedelta(hours=boundary - 0.5)
    assert lead_bucket(issue, start, end) == lead_bin(boundary)


def test_same_bin_prediction_outside_independently_observed_lead_range_falls_back():
    rows = synthetic_days()
    learner = ResidualLearner().fit(rows, EPOCH + timedelta(days=50))
    row = synthetic_days(first=50, count=1)[0]
    report = learner.status["wr"]["lead_bins"]["6-24h"]
    assert report["supported_lead_min_hours"] == 6.5
    assert report["supported_lead_max_hours"] == 17.5
    for lead in (6, 6.49, 17.51, 23.99):
        result = learner.predict("wr", {**row.features, "lead_hours": lead}, row.baseline_w, 2000)
        assert result.power_w == row.baseline_w
        assert result.status == "physics_lead_outside_validated_range"
    for lead in (6.5, 17.5):
        result = learner.predict("wr", {**row.features, "lead_hours": lead}, row.baseline_w, 2000)
        assert result.status.startswith("residual")


def coordinator(hass):
    config = SiteConfig(52, 13, "Europe/Berlin", (StringConfig("s", "i", 5, 30, 180),), (InverterConfig("i", 5, curtailed_entity_id="binary_sensor.test_control"),))
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    return AdaptiveSolarCoordinator(hass, entry, config, AsyncMock())


@pytest.mark.parametrize("energy", [True, False, 5.50001, 500, float("nan")])
async def test_corrupt_or_over_cap_stored_intervals_reject_entire_store(hass, energy):
    instance = coordinator(hass)
    payload = {**instance._stored(), "learning_feature_contract": LEARNING_FEATURE_CONTRACT,
               "archive": [archived()], "intervals": [measured()], "daily_snapshots": {}}
    payload["intervals"][0]["energy_kwh"] = energy
    instance._store.async_load = AsyncMock(return_value=payload)
    with freeze_time(NOW + timedelta(hours=2)):
        await instance.async_restore()
    assert instance.archive == instance.intervals == []
    assert instance.daily_snapshots == {}
    await instance.async_close()


@pytest.mark.parametrize("day,hours", [("2026-03-29", 23), ("2026-10-25", 25)])
@pytest.mark.parametrize("bad", ["boolean", "over_cap", "non_mapping"])
async def test_snapshot_cap_uses_real_dst_duration_and_rejects_bool(hass, day, hours, bad):
    instance = coordinator(hass)
    snapshot = {"issued_at": "2026-01-01T00:00:00+00:00", "energies": {"i": True if bad == "boolean" else 5 * hours * 1.1 + 0.001}}
    if bad == "non_mapping":
        snapshot["energies"] = ["i"]
    instance._store.async_load = AsyncMock(return_value={**instance._stored(),
        "learning_feature_contract": LEARNING_FEATURE_CONTRACT, "archive": [archived()], "intervals": [], "daily_snapshots": {day: snapshot}})
    with freeze_time(NOW + timedelta(hours=2)):
        await instance.async_restore()
    assert instance.archive == [] and instance.daily_snapshots == {}
    await instance.async_close()


@pytest.mark.parametrize("field,value,accepted", [("baseline_w", 5001, False), ("power_w", 5001, False),
                                                 ("inverter_id", "foreign", False), ("baseline_w", 5000, True)])
async def test_restored_forecast_must_match_inverter_boundary(hass, field, value, accepted):
    instance = coordinator(hass)
    row = {**archived(), "power_w": 1000, field: value}
    if field == "baseline_w":
        row["features"] = {**row["features"], "baseline_w": value}
    instance._store.async_load = AsyncMock(return_value={**instance._stored(),
        "learning_feature_contract": LEARNING_FEATURE_CONTRACT, "archive": [row], "intervals": [measured()], "daily_snapshots": {}})
    with freeze_time(NOW + timedelta(hours=2)):
        await instance.async_restore()
    assert instance.archive == ([row] if accepted else [])
    assert instance.intervals == ([measured()] if accepted else [])
    await instance.async_close()


@pytest.mark.parametrize("state,expected", [("on", "active"), ("off", "clear"), ("unavailable", "unknown")])
async def test_control_snapshot_exists_even_without_power_measurement(hass, state, expected):
    instance = coordinator(hass)
    hass.states.async_set("binary_sensor.test_control", state)
    observations = instance._observations(NOW)
    assert instance.input_quality["curtailment_i"] == expected
    assert any(row.curtailed and row.power_w is None and row.time == NOW for row in observations) == (state != "off")
    await instance.async_close()


@pytest.mark.parametrize("day,hours", [("2026-03-29", 23), ("2026-10-25", 25)])
async def test_valid_dst_snapshot_and_interval_at_the_live_tolerance_are_retained(hass, day, hours):
    from freezegun import freeze_time
    from zoneinfo import ZoneInfo

    instance = coordinator(hass)
    start = datetime.fromisoformat(day).replace(tzinfo=ZoneInfo("Europe/Berlin")).astimezone(UTC)
    payload = {**instance._stored(), "archive": [],
               "intervals": [measured(start, start + timedelta(hours=1), power=5500)],
               "daily_snapshots": {day: {"issued_at": (start - timedelta(hours=1)).isoformat(), "energies": {"i": 5 * hours * 1.1}}}}
    instance._store.async_load = AsyncMock(return_value=payload)
    with freeze_time(start + timedelta(hours=2)):
        await instance.async_restore()
    assert instance.intervals == payload["intervals"]
    assert instance.daily_snapshots == payload["daily_snapshots"]
    await instance.async_close()


@pytest.mark.parametrize("inverters,expected", [(3, [48.1, 72, 95.9]), (4, [48.1, 95.9]), (7, [72])])
async def test_archive_fixed_slot_budget_keeps_actual_bin_edges_and_middle(hass, inverters, expected):
    from custom_components.adaptive_solar.core.models import ForecastPoint, ForecastResult

    ids = [f"i{index}" for index in range(inverters)]
    config = SiteConfig(52, 13, "Europe/Berlin", tuple(StringConfig(f"s{index}", identifier, 5, 30, 180) for index, identifier in enumerate(ids)), tuple(InverterConfig(identifier, 5) for identifier in ids))
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    instance = AdaptiveSolarCoordinator(hass, entry, config, AsyncMock())
    point = ForecastPoint(NOW, NOW + timedelta(hours=1), ids[0], 1000, 1000, features={"baseline_w": 1000, "sun_elevation_deg": 45})
    for lead in (95.9, 80, 72, 60, 48.1):
        issue = NOW + timedelta(minutes=30) - timedelta(hours=lead)
        instance._archive_result(ForecastResult(issue, (point,)))
    assert sorted(row["features"]["lead_hours"] for row in instance.archive) == pytest.approx(expected)
    # Repeated capture cannot manufacture more origins; night/zero baselines
    # never spend the bounded training archive budget.
    instance._archive_result(ForecastResult(issue, (point,)))
    night = replace(point, start=NOW + timedelta(hours=1), end=NOW + timedelta(hours=2), features={"baseline_w": 1000, "sun_elevation_deg": -1})
    instance._archive_result(ForecastResult(issue, (night,)))
    assert len(instance.archive) == len(expected)
    await instance.async_close()


def test_independent_representative_multiday_origins_support_60h_without_inflating_actual_hours():
    rows = synthetic_days()
    arms = [replace(row, issued_at=row.start + (row.end - row.start) / 2 - timedelta(hours=lead),
                    features={**row.features, "lead_hours": lead})
            for row in rows for lead in (48.1, 72, 95.9)]
    learner = ResidualLearner().fit(arms, EPOCH + timedelta(days=50))
    report = learner.status["wr"]
    assert report["state"] == "active"
    assert report["unique_target_hours"] == 600
    assert report["unique_intervals"] == 600
    assert report["issues"] == 1800
    assert report["lead_bins"]["48-96h"]["supported_lead_min_hours"] == 48.1
    assert report["lead_bins"]["48-96h"]["supported_lead_max_hours"] == 95.9
    row = synthetic_days(first=55, count=1)[0]
    result = learner.predict("wr", {**row.features, "lead_hours": 60}, row.baseline_w, 2000)
    assert result.status.startswith("residual")
    assert abs(result.power_w - row.actual_w) < abs(row.baseline_w - row.actual_w)
    assert learner.predict("wr", {**row.features, "lead_hours": 48.01}, row.baseline_w, 2000).status == "physics_lead_outside_validated_range"
