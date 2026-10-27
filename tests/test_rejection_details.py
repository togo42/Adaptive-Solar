"""Rejection provenance is bounded and observational, including native HA output."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
import json
from unittest.mock import AsyncMock, patch

from freezegun import freeze_time
import pytest

from custom_components.adaptive_solar.coordinator import join_training
from custom_components.adaptive_solar.core.learning import ResidualLearner
from custom_components.adaptive_solar.core.models import WeatherForecast, WeatherPoint
from custom_components.adaptive_solar.core.rejection import RejectionDetails, detail_time
from custom_components.adaptive_solar.diagnostics import async_get_config_entry_diagnostics
from custom_components.adaptive_solar.sensor import AdaptiveSolarSensor
from tests.test_learning import EPOCH, synthetic_days
from tests.test_learning_persistence import coordinator, evidence, NOW
from tests.test_training_alignment import archived, measured


def corrupt(row, **changes):
    """Fault injection below the normal validated TrainingSample constructor."""
    row = deepcopy(row)
    for name, value in changes.items():
        object.__setattr__(row, name, value)
    return row


def test_join_details_are_the_original_unique_outcomes_not_another_sample_policy():
    good = archived()
    bad_origin = {**good, "issued_at": (NOW + timedelta(minutes=1)).isoformat()}
    pending = archived(start=NOW + timedelta(hours=2))
    rejected = archived(start=NOW - timedelta(hours=1), duration=600, lead=-1)
    archive = [good, bad_origin, good, pending, rejected, rejected]
    expected = join_training(archive, [measured()], as_of=NOW + timedelta(hours=1))
    counts, details = {}, {}
    actual = join_training(archive, [measured()], as_of=NOW + timedelta(hours=1),
                           diagnostics=counts, rejection_details=details)
    assert actual == expected
    assert counts["i"]["accepted_target_cells"] == counts["i"]["pending_target_cells"] == 1
    assert counts["i"]["rejected_target_cells"] == details["i"]["total"] == 1
    assert details["i"]["items"] == [{"start": detail_time(NOW - timedelta(hours=1)),
        "end": detail_time(NOW - timedelta(minutes=50)),
        "reasons": ["issued_after_target_start", "target_shorter_than_minimum"]}]
    only_details = {}
    assert join_training(archive, [measured()], as_of=NOW + timedelta(hours=1),
                         rejection_details=only_details) == expected
    assert only_details == details


def test_future_receipt_and_regime_origins_do_not_multiply_target_details():
    row = archived()
    ghi = {**row, "issued_at": (NOW - timedelta(hours=1)).isoformat(),
        "features": {**row["features"], "ghi_regime": 1,
        "ghi_nowcast_gain": 1.1, "ghi_observation_age_seconds": 10}}
    interval = {**measured(), "observed_at": (NOW + timedelta(hours=2)).isoformat()}
    counts, details = {}, {}
    join_training([row, ghi], [interval], as_of=NOW + timedelta(hours=1),
                  diagnostics=counts, rejection_details=details)
    assert counts["i"]["rejected_target_cells"] == details["i"]["total"] == 1
    assert details["i"]["items"][0]["reasons"] == ["observation_not_yet_available"]
    assert len(join_training([row, ghi], [interval], as_of=NOW + timedelta(hours=2),
                            diagnostics=counts, rejection_details=details)) == 2
    assert details["i"] == {"total": 0, "truncated": False, "items": []}


def test_more_than_50_targets_are_counted_fully_and_selected_deterministically_per_stage():
    rows = [archived(start=NOW - timedelta(hours=h)) for h in range(1, 81)]
    rows += [{**rows[0], "inverter_id": "separate"}]
    for source in (rows, rows[::-1], rows[::2] + rows[1::2]):
        counts, details = {}, {}
        join_training(source, [], as_of=NOW, diagnostics=counts, rejection_details=details)
        assert details["i"]["total"] == counts["i"]["rejected_target_cells"] == 80
        assert details["i"]["truncated"] is True and len(details["i"]["items"]) == 50
        assert details["i"]["items"][0]["end"] == detail_time(NOW)
        assert details["i"]["items"][-1]["end"] == detail_time(NOW - timedelta(hours=49))
        assert details["separate"]["total"] == 1


@pytest.mark.parametrize("changes,reason", [
    ({"issued_at": None}, "invalid_issued_at"),
    ({"start": "not a date"}, "invalid_start"),
    ({"end": datetime(2026, 1, 1)}, "invalid_end"),
    ({"observed_at": None}, "invalid_observed_at"),
    ({"issued_at": EPOCH + timedelta(days=1)}, "issued_after_target_start"),
    ({"end": EPOCH}, "nonpositive_target_duration"),
    ({"observed_at": EPOCH}, "observation_before_target_end"),
    ({"observed_at": EPOCH + timedelta(days=99)}, "observation_not_yet_available"),
    ({"curtailed": True}, "curtailed"),
    ({"baseline_w": float("nan")}, "invalid_baseline"),
    ({"actual_w": float("inf")}, "invalid_actual_power"),
    ({"baseline_w": 0}, "baseline_out_of_range"),
    ({"actual_w": -1}, "actual_power_out_of_range"),
    ({"actual_w": 10000}, "actual_power_out_of_range"),
    ({"features": None}, "invalid_feature_vector"),
])
def test_input_gate_explains_actual_rejections_without_inventing_times(changes, reason):
    row = corrupt(synthetic_days(count=1)[0], **changes)
    details = {}
    learner = ResidualLearner(output_caps={"wr": 2000}).fit([row], EPOCH + timedelta(days=50), diagnostics=details)
    assert learner.status["wr"]["rejected_rows"] == details["wr"]["total"] == 1
    item = details["wr"]["items"][0]
    assert item["reasons"] == [reason]
    for name in ("start", "end", "issued_at"):
        assert item[name] == detail_time(getattr(row, name))
    json.dumps(details, allow_nan=False)


@pytest.mark.parametrize("feature,value,reason", [
    ("wind_m_s", None, "invalid_feature_vector"),
    ("ghi_regime", 2, "invalid_feature_vector"),
    ("beam_shade_factor", -1, "invalid_shade_factor"),
    ("output_cap_w", 1000, "invalid_output_cap"),
    ("sun_elevation_deg", 0, "nonpositive_sun_elevation"),
    ("lead_hours", -1, "negative_lead_time"),
    ("baseline_w", 100, "baseline_feature_mismatch"),
    ("target_duration_seconds", 1, "invalid_measurement_alignment"),
    ("measurement_edge_seconds", "missing", "invalid_measurement_alignment"),
])
def test_feature_gate_short_circuits_safely_and_unknown_regime_remains_unknown(feature, value, reason):
    base = synthetic_days(count=1)[0]
    features = {**base.features, feature: value}
    if value is None:
        del features[feature]
    row = corrupt(base, features=features)
    details = {}
    learner = ResidualLearner(output_caps={"wr": 2000}).fit([row], EPOCH + timedelta(days=50), diagnostics=details)
    assert learner.status["wr"]["rejected_rows"] == 1
    item = details["wr"]["items"][0]
    assert item["reasons"] == [reason]
    assert item["regime"] == ("unknown" if feature == "ghi_regime" else "nwp")


def test_raw_row_totals_duplicates_reason_union_and_all_sort_tie_breakers():
    base = synthetic_days(count=1)[0]
    bad = corrupt(base, features={})
    blocked = replace(base, curtailed=True)
    unknown = corrupt(base, features={"ghi_regime": 2})
    rows = [bad] * 90 + [blocked, unknown]
    views = []
    for source in (rows, rows[::-1]):
        details = {}
        learner = ResidualLearner().fit(source, EPOCH + timedelta(days=50), diagnostics=details)
        assert learner.status["wr"]["rejected_rows"] == details["wr"]["total"] == 92
        assert details["wr"]["truncated"] is True and len(details["wr"]["items"]) == 2
        nwp = next(item for item in details["wr"]["items"] if item["regime"] == "nwp")
        assert nwp["reasons"] == ["curtailed", "invalid_feature_vector"]
        views.append(details)
    assert views[0] == views[1]
    collector = RejectionDetails()
    candidates = [(base.start + timedelta(minutes=i % 2), base.end,
                   base.issued_at + timedelta(seconds=i), "ghi" if i % 2 else "nwp") for i in range(90)]
    for start, end, issue, regime in candidates[::-1]:
        collector.add(start, end, ["curtailed"], issued_at=issue, regime=regime)
    assert len(collector._items) == 50  # Memory is bounded, not just final JSON.
    first = collector.to_dict()
    other = RejectionDetails()
    for start, end, issue, regime in candidates:
        other.add(start, end, ["curtailed"], issued_at=issue, regime=regime)
    assert other.to_dict() == first


def test_learner_caps_actual_row_details_at_50_and_keeps_stage_totals_independent():
    rows = [corrupt(row, features={}) for row in synthetic_days(count=6)]
    rows.append(corrupt(rows[0], inverter_id="separate"))
    results = []
    for source in (rows, rows[::-1]):
        details = {}
        learner = ResidualLearner().fit(source, EPOCH + timedelta(days=50), diagnostics=details)
        assert details["wr"]["total"] == learner.status["wr"]["rejected_rows"] == 72
        assert len(details["wr"]["items"]) == 50 and details["wr"]["truncated"] is True
        assert details["separate"]["total"] == learner.status["separate"]["rejected_rows"] == 1
        results.append(details)
    assert results[0] == results[1]


def test_unknown_times_sort_last_and_regime_breaks_an_otherwise_identical_key():
    base = synthetic_days(count=1)[0]
    collectors = []
    for regimes in (("nwp", "ghi", "unknown"), ("unknown", "ghi", "nwp")):
        collector = RejectionDetails()
        collector.add(None, None, ["invalid_end"], issued_at=None, regime="unknown")
        for regime in regimes:
            collector.add(base.start, base.end, ["invalid_feature_vector"], issued_at=base.issued_at, regime=regime)
        collectors.append(collector.to_dict())
    assert collectors[0] == collectors[1]
    assert collectors[0]["items"][-1]["end"] is None
    assert [item["regime"] for item in collectors[0]["items"][:3]] == ["unknown", "nwp", "ghi"]


async def test_new_local_day_refreshes_cutoff_and_finalizes_previously_pending_target(hass):
    instance, _ = coordinator(hass)
    instance.client.async_forecasts.return_value = (WeatherForecast("best_match", NOW, (
        WeatherPoint(NOW, NOW + timedelta(hours=1), 600, 400, 200, 20, 2, 30),)),)
    for expected_targets, cutoff in enumerate((NOW, NOW + timedelta(days=1))):
        with freeze_time(cutoff):
            await instance._async_update_data()
        details = instance.learner_status["i"]["training_quality"]["rejection_details"]
        assert details["evaluated_at"] == detail_time(cutoff)
        assert details["targets"]["total"] == expected_targets
        assert details["rows"]["total"] == 0
    await instance.async_close()


@pytest.mark.parametrize("stamp", ["2026-03-29T01:30:00+01:00", "2026-03-29T03:30:00+02:00",
                                   "2026-10-25T02:30:00+02:00", "2026-10-25T02:30:00+01:00"])
def test_original_dst_times_are_unambiguous_utc_without_wall_clock_reinterpretation(stamp):
    start = datetime.fromisoformat(stamp)
    end = start + timedelta(hours=1)
    collector = RejectionDetails()
    collector.add(start, end, ["curtailed"])
    item = collector.to_dict()["items"][0]
    assert datetime.fromisoformat(item["start"]) == start
    assert datetime.fromisoformat(item["end"]) - datetime.fromisoformat(item["start"]) == timedelta(hours=1)


def test_existing_counted_shade_rejection_has_a_distinct_reason_but_other_filters_do_not():
    base = synthetic_days(count=1)[0]
    old = replace(base, features={**base.features, "beam_shade_factor": 1.0})
    newer = replace(base, issued_at=base.issued_at + timedelta(hours=1),
                    features={**base.features, "beam_shade_factor": 0.5})
    details = {}
    learner = ResidualLearner().fit([old, newer], EPOCH + timedelta(days=50), diagnostics=details)
    assert learner.status["wr"]["rejected_rows"] == details["wr"]["total"] == 1
    assert details["wr"]["items"][0]["reasons"] == ["incompatible_shade_baseline"]
    # Conflicting labels are a later filter and never incremented rejected_rows.
    learner.fit([base, replace(base, actual_w=base.actual_w + 1)], EPOCH + timedelta(days=50), diagnostics=details)
    assert learner.status["wr"]["issues"] == learner.status["wr"]["rejected_rows"] == details["wr"]["total"] == 0


@pytest.mark.parametrize("unshaded", [False, True])
def test_collection_changes_neither_fits_predictions_nor_validation_or_existing_counts(unshaded):
    rows = synthetic_days(unshaded=unshaded)
    blocked = [replace(row, curtailed=True) for row in rows[:60]]
    cutoff = EPOCH + timedelta(days=50)
    plain = ResidualLearner().fit(rows + blocked, cutoff)
    details = {}
    traced = ResidualLearner().fit(iter(rows + blocked), cutoff, diagnostics=details)
    assert traced.status == plain.status
    for row in synthetic_days(first=50, count=1):
        assert traced.predict("wr", row.features, row.baseline_w, 2000) == plain.predict("wr", row.features, row.baseline_w, 2000)
    assert details["wr"]["total"] == 60  # Validation rejection adds no fake row.
    traced.fit([], cutoff, diagnostics=details)
    assert details == {} and traced.status == {}


async def test_coordinator_cache_freezes_the_common_snapshot_and_revision_refreshes_it(hass):
    instance, _ = coordinator(hass)
    payload = evidence(instance)
    instance.archive = payload["archive"]
    instance.client.async_forecasts.return_value = (WeatherForecast("best_match", NOW, (
        WeatherPoint(NOW, NOW + timedelta(hours=1), 600, 400, 200, 20, 2, 30),)),)
    with freeze_time(NOW + timedelta(minutes=30)):
        await instance._async_update_data()
    first = deepcopy(instance.learner_status["i"]["training_quality"])
    assert first["alignment"]["pending_target_cells"] == 1
    assert first["rejection_details"]["targets"]["total"] == 0
    with freeze_time(NOW + timedelta(hours=2)):
        await instance._async_update_data()
    assert instance.learner_status["i"]["training_quality"]["rejection_details"] == first["rejection_details"]
    assert instance.learner_status["i"]["training_quality"]["alignment"] == first["alignment"]
    instance._append_interval(payload["intervals"][0])
    with freeze_time(NOW + timedelta(hours=2, minutes=5)):
        await instance._async_update_data()
    quality = instance.learner_status["i"]["training_quality"]
    assert quality["rejection_details"]["evaluated_at"] == detail_time(NOW + timedelta(hours=2, minutes=5))
    assert quality["alignment"]["accepted_target_cells"] == 1
    assert quality["rejection_details"]["rows"]["total"] == instance.learner_status["i"]["rejected_rows"] == 2
    assert {item["regime"] for item in quality["rejection_details"]["rows"]["items"]} == {"nwp", "ghi"}
    await instance.async_close()


async def test_native_ha_sensor_and_redacted_diagnostics_transport_v1(hass, enable_custom_integrations):
    instance, entry = coordinator(hass)
    weather = WeatherForecast("best_match", NOW, (WeatherPoint(NOW, NOW + timedelta(hours=1), 600, 400, 200, 20, 2, 30),))
    with freeze_time(NOW), patch("custom_components.adaptive_solar.weather.OpenMeteoClient.async_forecasts", new=AsyncMock(return_value=(weather,))):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        qualities = [state for state in hass.states.async_all("sensor") if state.attributes.get("device_class") == "enum"]
        assert len(qualities) == 1
        report = qualities[0].attributes["learning"]["i"]
        details = report["training_quality"]["rejection_details"]
        assert details == {"schema_version": 1, "evaluated_at": detail_time(NOW),
            "targets": {"total": 0, "truncated": False, "items": []},
            "rows": {"total": 0, "truncated": False, "items": []}}
        diag = await async_get_config_entry_diagnostics(hass, entry)
        assert diag["learning"]["i"]["training_quality"]["rejection_details"] == details
        active = entry.runtime_data
        before = {**archived(start=NOW - timedelta(hours=2)), "features": {"baseline_w": 2000, "sun_elevation_deg": 45}}
        with_measurement = {**archived(start=NOW - timedelta(hours=1)), "features": {"baseline_w": 2000, "sun_elevation_deg": 45}}
        active.archive = [before, with_measurement]
        active._append_interval(measured(start=NOW - timedelta(hours=1), end=NOW))
        await active.async_request_refresh()
        await hass.async_block_till_done()
        state = hass.states.get(qualities[0].entity_id)
        report = state.attributes["learning"]["i"]
        details = report["training_quality"]["rejection_details"]
        assert details["targets"]["total"] == report["training_quality"]["alignment"]["rejected_target_cells"] == 1
        assert details["rows"]["total"] == report["rejected_rows"] == 1
        assert details["targets"]["items"][0]["reasons"] == ["no_whole_measurement_inside_target"]
        assert details["rows"]["items"][0]["reasons"] == ["invalid_feature_vector"]
        diag = await async_get_config_entry_diagnostics(hass, entry)
        assert diag["learning"]["i"]["training_quality"]["rejection_details"] == details
        encoded = json.dumps(details, allow_nan=False)
        assert all(word not in encoded for word in ("entity_id", "latitude", "longitude"))
        assert "learning" in AdaptiveSolarSensor._unrecorded_attributes
        assert await hass.config_entries.async_unload(entry.entry_id)
    await instance.async_close()
