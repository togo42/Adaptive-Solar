"""Stored solar-window snapshots are bounded projections, not learning events."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from unittest.mock import patch
from zoneinfo import ZoneInfo

from freezegun import freeze_time
import pytest

from custom_components.adaptive_solar.core.shading import BeamShadeTable

NOW = datetime(2026, 6, 21, 10, tzinfo=UTC)
ITEM_KEYS = {
    "azimuth_bin_deg", "elevation_bin_deg", "transmittance", "candidate_transmittance",
    "daily_mad", "samples", "days", "excluded_time_samples", "newest_sample_age_days",
    "unqualified_legacy_samples", "released", "release_reason", "stored_samples",
    "expired_samples", "unavailable_samples",
}


def qualified(table, stage="i", azimuth=180, elevation=40, factor=0.5):
    """Five immutable quarters on two days, all available at their observation."""
    for age in (timedelta(days=1, minutes=30), timedelta(days=1, minutes=15),
                timedelta(days=1), timedelta(minutes=15), timedelta()):
        at = NOW - age
        assert table.record(stage, azimuth, elevation, at, factor, as_of=at)


def legacy_windows():
    return {"180:40": [{"quarter_hour": (NOW - timedelta(days=day)).isoformat(), "factor": 0.1}
                       for day in range(5)],
            "90:20": [{"quarter_hour": NOW.isoformat(), "factor": 0.2}]}


def assert_matches_status(table, stage, snapshot, as_of):
    """Compare semantics with the unchanged, public current-window API."""
    assert snapshot["filled_bins"] == table.filled_bins(stage, as_of=as_of)
    assert snapshot["filled_bins"] == sum(item["released"] for item in snapshot["items"])
    for item in snapshot["items"]:
        assert set(item) == ITEM_KEYS  # No raw sample/release-event arrays.
        status = table.status_for(stage, item["azimuth_bin_deg"], item["elevation_bin_deg"], as_of=as_of)
        for key in ("transmittance", "released", "release_reason", "samples", "days",
                    "excluded_time_samples", "newest_sample_age_days"):
            assert item[key] == status[key]
        for key in ("candidate_transmittance", "daily_mad"):
            assert item[key] == (status[key] if item["samples"] else None)
        assert item["samples"] + item["expired_samples"] + item["unavailable_samples"] == item["stored_samples"]
        assert item["excluded_time_samples"] == item["expired_samples"] + item["unavailable_samples"]
        assert item["transmittance"] == table.transmittance(
            stage, item["azimuth_bin_deg"], item["elevation_bin_deg"], as_of=as_of)


def test_empty_stage_is_an_explicit_empty_snapshot_not_a_fabricated_grid():
    table = BeamShadeTable()
    assert table.window_diagnostics("i", as_of=NOW) == {
        "schema_version": 1, "evaluated_at": NOW.isoformat(), "scope": "stored_solar_windows",
        "azimuth_step_deg": 10, "elevation_step_deg": 5, "max_items": 648,
        "total": 0, "truncated": False, "filled_bins": 0,
        "policy": {"min_samples": 5, "min_days": 2, "max_age_days": 45, "max_daily_mad": 0.15},
        "items": [],
    }
    assert table.to_dict() == {"schema": 3, "inverters": {}, "released": {}}


@pytest.mark.parametrize("factor", [0.0, 0.5, 1.0])
def test_qualified_zero_partial_and_learned_neutral_are_all_released(factor):
    table = BeamShadeTable()
    qualified(table, factor=factor)
    snapshot = table.window_diagnostics("i", as_of=NOW)
    item, = snapshot["items"]
    assert snapshot["total"] == snapshot["filled_bins"] == 1
    assert item["released"] is True
    assert item["release_reason"] == "qualified"
    assert item["transmittance"] == item["candidate_transmittance"] == factor
    assert item["daily_mad"] == item["newest_sample_age_days"] == 0
    assert item["samples"] == item["stored_samples"] == 5 and item["days"] == 2
    assert_matches_status(table, "i", snapshot, NOW)


@pytest.mark.parametrize(("ages", "factors", "reason", "candidate", "mad", "days"), [
    ([1, 0], [0.5, 0.5], "insufficient_samples", 0.5, 0.0, 2),
    ([0, 0, 0, 0, 0], [0.5] * 5, "insufficient_days", 0.5, 0.0, 1),
    ([1, 1, 1, 0, 0], [0.1, 0.1, 0.1, 0.9, 0.9], "unstable_daily_transmittance", 0.5, 0.4, 2),
])
def test_unreleased_evidence_reports_its_candidate_but_applies_neutral(ages, factors, reason, candidate, mad, days):
    table = BeamShadeTable()
    for index, (age, factor) in enumerate(zip(ages, factors, strict=True)):
        at = NOW - timedelta(days=age, minutes=15 * (len(ages) - index))
        assert table.record("i", 180, 40, at, factor, as_of=NOW)
    snapshot = table.window_diagnostics("i", as_of=NOW)
    item, = snapshot["items"]
    assert item["released"] is False and item["transmittance"] == 1.0
    assert item["release_reason"] == reason and item["days"] == days
    assert item["candidate_transmittance"] == pytest.approx(candidate)
    assert item["daily_mad"] == pytest.approx(mad)
    assert snapshot["filled_bins"] == 0
    assert_matches_status(table, "i", snapshot, NOW)


def test_candidate_is_daily_balanced_not_the_pooled_sample_median():
    table = BeamShadeTable()
    for index in range(4):
        at = NOW - timedelta(days=1, minutes=15 * index)
        assert table.record("i", 180, 40, at, 0.4, as_of=at)
    assert table.record("i", 180, 40, NOW, 0.6, as_of=NOW)
    item, = table.window_diagnostics("i", as_of=NOW)["items"]
    assert item["candidate_transmittance"] == pytest.approx(0.5)
    assert item["transmittance"] == pytest.approx(0.5)
    assert item["daily_mad"] == pytest.approx(0.1)
    assert item["released"] is True


def test_applied_release_is_not_replaced_by_the_current_candidate_on_read():
    table = BeamShadeTable()
    qualified(table)
    stored = table.to_dict()
    stored["released"]["i"]["180:40"][-1]["factor"] = 0.4
    table = BeamShadeTable.from_dict(stored)
    item, = table.window_diagnostics("i", as_of=NOW)["items"]
    assert item["candidate_transmittance"] == 0.5
    assert item["transmittance"] == 0.4
    assert table.to_dict() == stored


def test_expired_windows_remain_visible_without_stale_candidate_or_release():
    table = BeamShadeTable()
    qualified(table)
    future = NOW + timedelta(days=46)
    before = deepcopy(table.to_dict())
    snapshot = table.window_diagnostics("i", as_of=future)
    item, = snapshot["items"]
    assert item["released"] is False and item["transmittance"] == 1.0
    assert item["samples"] == item["days"] == 0
    assert item["stored_samples"] == item["expired_samples"] == item["excluded_time_samples"] == 5
    assert item["candidate_transmittance"] is item["daily_mad"] is item["newest_sample_age_days"] is None
    assert table.to_dict() == before  # Reading must not prune expired evidence.
    assert_matches_status(table, "i", snapshot, future)


def test_exact_45_day_boundary_is_inclusive_and_does_not_refresh_release():
    table = BeamShadeTable()
    qualified(table)
    at = NOW + timedelta(days=45)
    snapshot = table.window_diagnostics("i", as_of=at)
    item, = snapshot["items"]
    assert item["samples"] == 1 and item["expired_samples"] == 4
    assert item["newest_sample_age_days"] == 45.0
    assert item["released"] is False
    assert_matches_status(table, "i", snapshot, at)


def test_legacy_only_and_mixed_windows_have_local_counts_and_no_invented_qualification():
    table = BeamShadeTable.from_dict({"schema": 1, "inverters": {"i": legacy_windows()}})
    initial = table.window_diagnostics("i", as_of=NOW)
    assert initial["total"] == 2 and initial["filled_bins"] == 0
    assert [item["unqualified_legacy_samples"] for item in initial["items"]] == [1, 5]
    for item in initial["items"]:
        assert item["samples"] == item["stored_samples"] == 0
        assert item["transmittance"] == 1 and not item["released"]
        assert item["candidate_transmittance"] is item["daily_mad"] is None
    qualified(table)
    assert table.record("i", 270, 30, NOW, 0.8, as_of=NOW)
    snapshot = table.window_diagnostics("i", as_of=NOW)
    assert [(item["azimuth_bin_deg"], item["elevation_bin_deg"]) for item in snapshot["items"]] == [
        (90, 20), (180, 40), (270, 30)]
    assert [item["unqualified_legacy_samples"] for item in snapshot["items"]] == [1, 5, 0]
    assert snapshot["filled_bins"] == 1
    assert_matches_status(table, "i", snapshot, NOW)
    # Compatibility: old status deliberately has a STAGE-wide legacy count.
    assert table.status_for("i", 270, 30, as_of=NOW)["unqualified_legacy_samples"] == 6


def test_accepted_noncanonical_legacy_keys_count_evidence_in_their_numeric_window():
    # The existing reader accepts zero-padded keys. A display read must neither
    # drop their counts nor fabricate a second copy of the same solar window.
    canonical = legacy_windows()["180:40"]
    table = BeamShadeTable.from_dict({"schema": 1, "inverters": {"i": {
        "180:40": canonical, "0180:040": canonical[:2],
    }}})
    before = deepcopy(table.to_dict())
    snapshot = table.window_diagnostics("i", as_of=NOW)
    item, = snapshot["items"]
    assert (item["azimuth_bin_deg"], item["elevation_bin_deg"]) == (180, 40)
    assert item["unqualified_legacy_samples"] == 7
    assert sum(row["unqualified_legacy_samples"] for row in snapshot["items"]) == (
        table.status_for("i", as_of=NOW)["unqualified_legacy_samples"])
    assert item["samples"] == 0 and item["released"] is False
    assert table.to_dict() == before


def test_stage_selection_isolated_and_unknown_stage_does_not_create_storage():
    table = BeamShadeTable()
    qualified(table, "east", 90, 20, 0.0)
    qualified(table, "west", 270, 30, 1.0)
    before = deepcopy(table.__dict__)
    for stage, azimuth, factor in (("east", 90, 0.0), ("west", 270, 1.0)):
        item, = table.window_diagnostics(stage, as_of=NOW)["items"]
        assert item["azimuth_bin_deg"] == azimuth and item["transmittance"] == factor
    assert table.window_diagnostics("missing", as_of=NOW)["items"] == []
    assert table.__dict__ == before


def test_receipt_and_observation_cutoffs_are_independent_of_stored_release_time():
    table = BeamShadeTable()
    for index in range(5):
        at = NOW - timedelta(days=1, minutes=15 * index)
        assert table.record("i", 180, 40, at, 0.5, as_of=at)
    # A second measurement day exists, but its receipt is delayed by one hour.
    receipt = NOW + timedelta(hours=1)
    assert table.record("i", 180, 40, NOW, 0.5, as_of=receipt)
    # A stored future observation must also stay excluded at the earlier cutoff.
    assert table.record("i", 180, 40, NOW + timedelta(days=1), 0.5, as_of=NOW + timedelta(days=1))
    before = deepcopy(table.to_dict())
    for as_of, samples, days, unavailable, released in (
        (NOW - timedelta(seconds=1), 5, 1, 2, False),
        (NOW, 5, 1, 2, False),
        (receipt, 6, 2, 1, True),
        (NOW + timedelta(days=1), 7, 3, 0, True),
    ):
        snapshot = table.window_diagnostics("i", as_of=as_of)
        item, = snapshot["items"]
        assert (item["samples"], item["days"], item["unavailable_samples"], item["released"]) == (
            samples, days, unavailable, released)
        if as_of == receipt:
            assert item["newest_sample_age_days"] == pytest.approx(1 / 24)
        assert_matches_status(table, "i", snapshot, as_of)
    assert table.to_dict() == before


def test_expired_and_unavailable_categories_partition_stored_samples_without_overlap():
    rows = []
    for observed, available in (
        (NOW - timedelta(days=46), NOW + timedelta(days=1)),  # Expired takes precedence.
        (NOW - timedelta(days=1), NOW),
        (NOW - timedelta(minutes=15), NOW + timedelta(seconds=1)),
        (NOW + timedelta(minutes=15), NOW + timedelta(minutes=15)),
    ):
        rows.append({"quarter_hour": observed.isoformat(), "observed_at": observed.isoformat(),
                     "available_at": available.isoformat(), "factor": 0.5})
    table = BeamShadeTable.from_dict({"schema": 3, "inverters": {"i": {"180:40": rows}}, "released": {}})
    snapshot = table.window_diagnostics("i", as_of=NOW)
    item, = snapshot["items"]
    assert item["stored_samples"] == 4
    assert item["samples"] == 1 and item["expired_samples"] == 1 and item["unavailable_samples"] == 2
    assert item["excluded_time_samples"] == 3
    assert item["newest_sample_age_days"] == 1
    assert_matches_status(table, "i", snapshot, NOW)


def test_future_release_is_not_backdated_even_when_all_samples_are_eligible():
    table = BeamShadeTable()
    qualified(table)
    stored = table.to_dict()
    stored["released"]["i"]["180:40"] = [{"at": (NOW + timedelta(hours=1)).isoformat(), "factor": 0.5}]
    table = BeamShadeTable.from_dict(stored)
    snapshot = table.window_diagnostics("i", as_of=NOW)
    item, = snapshot["items"]
    assert item["samples"] == 5 and item["candidate_transmittance"] == 0.5
    assert item["release_reason"] == "no_release_available_at_as_of"
    assert item["transmittance"] == 1.0 and item["released"] is False
    assert_matches_status(table, "i", snapshot, NOW)
    assert table.to_dict() == stored


def test_snapshots_and_mutated_outputs_never_change_table_or_release_history():
    table = BeamShadeTable.from_dict({"schema": 1, "inverters": {"i": legacy_windows()}})
    qualified(table)
    before = deepcopy(table.__dict__)
    expected = table.window_diagnostics("i", as_of=NOW)
    with patch.object(table, "record", side_effect=AssertionError("diagnostic recorded evidence")), \
         patch.object(table, "_refresh_release", side_effect=AssertionError("diagnostic refreshed release")):
        snapshot = table.window_diagnostics("i", as_of=NOW)
        snapshot["policy"]["min_samples"] = 1
        snapshot["items"][0]["transmittance"] = 0.123
        snapshot["items"].append({"private": "caller modification"})
        table.window_diagnostics("i", as_of=NOW + timedelta(days=100))
        table.window_diagnostics("missing", as_of=NOW)
        assert table.window_diagnostics("i", as_of=NOW) == expected
    assert table.__dict__ == before


def test_schema3_json_roundtrip_preserves_snapshot_and_original_storage_shape():
    table = BeamShadeTable.from_dict({"schema": 2, "inverters": {"i": legacy_windows()}})
    qualified(table)
    assert table.record("i", 270, 30, NOW, 0.2, as_of=NOW)
    before = deepcopy(table.to_dict())
    snapshot = table.window_diagnostics("i", as_of=NOW)
    restored = BeamShadeTable.from_dict(json.loads(json.dumps(before)), inverter_ids={"i"})
    assert restored.to_dict() == before == table.to_dict()
    assert set(before) == {"schema", "inverters", "released", "unqualified_legacy"}
    assert restored.window_diagnostics("i", as_of=NOW) == snapshot


def test_all_648_valid_windows_are_returned_once_in_numeric_order_not_insertion_order():
    table = BeamShadeTable()
    coordinates = [(azimuth, elevation) for azimuth in range(0, 360, 10) for elevation in range(0, 90, 5)]
    for azimuth, elevation in reversed(coordinates):
        qualified(table, azimuth=azimuth, elevation=elevation, factor=(azimuth // 10 % 3) / 2)
    before = deepcopy(table.to_dict())
    snapshot = table.window_diagnostics("i", as_of=NOW)
    assert snapshot["total"] == snapshot["max_items"] == snapshot["filled_bins"] == 648
    assert snapshot["truncated"] is False
    assert [(item["azimuth_bin_deg"], item["elevation_bin_deg"]) for item in snapshot["items"]] == coordinates
    assert snapshot == table.window_diagnostics("i", as_of=NOW)
    assert table.to_dict() == before
    assert_matches_status(table, "i", snapshot, NOW)


@pytest.mark.parametrize("as_of", [None, NOW.astimezone(ZoneInfo("Europe/Berlin"))])
def test_evaluated_at_is_utc_and_default_cutoff_is_the_current_instant(as_of):
    table = BeamShadeTable()
    qualified(table)
    with freeze_time(NOW):
        assert table.window_diagnostics("i", as_of=as_of) == table.window_diagnostics("i", as_of=NOW)


@pytest.mark.parametrize("date", [(2026, 3, 29), (2026, 10, 25)])
def test_both_dst_transitions_measure_age_in_elapsed_utc_days(date):
    at = datetime(*date, 12, tzinfo=ZoneInfo("Europe/Berlin"))
    previous = at.astimezone(UTC) - timedelta(days=1)
    table = BeamShadeTable()
    assert table.record("i", 180, 40, previous, 0.5, as_of=previous)
    snapshot = table.window_diagnostics("i", as_of=at)
    item, = snapshot["items"]
    assert snapshot["evaluated_at"] == at.astimezone(UTC).isoformat()
    assert item["newest_sample_age_days"] == 1.0
    assert item["samples"] == 1


def test_status_for_keeps_its_exact_existing_shape_and_no_sample_placeholders():
    table = BeamShadeTable.from_dict({"schema": 1, "inverters": {"i": legacy_windows()}})
    assert table.status_for("i", 270, 30, as_of=NOW, last_rejection="low_beam") == {
        "azimuth_bin_deg": 270, "elevation_bin_deg": 30, "transmittance": 1.0,
        "candidate_transmittance": 1.0, "daily_mad": 0.0, "unqualified_legacy_samples": 6,
        "samples": 0, "days": 0, "excluded_time_samples": 0, "newest_sample_age_days": None,
        "max_age_days": 45, "release_reason": "insufficient_samples", "released": False,
        "filled_bins": 0, "last_rejection": "low_beam",
    }
