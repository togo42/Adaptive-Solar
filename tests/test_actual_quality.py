"""Whole-hour evidence, explicit source qualification and causal mask revision."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from custom_components.adaptive_solar.const import MEASUREMENT_CONTRACT
from custom_components.adaptive_solar.core.actual_quality import BINDINGS_SCHEMA, build_quality, digest
from custom_components.adaptive_solar.core.archive import canonical_bytes
from custom_components.adaptive_solar.core.models import InverterConfig, SiteConfig, StringConfig


def envelope(kind, payload, sequence, received, *, source="test-source", generation=None):
    event = {"schema": 1, "generation": generation or str(UUID(int=1)), "sequence": sequence,
             "event_id": str(UUID(int=sequence + 100)), "kind": kind,
             "received_at": received.isoformat(), "payload": payload}
    event["sha256"] = hashlib.sha256(canonical_bytes(event)).hexdigest()
    return {**event, "source": source}


def rehash(event):
    event["sha256"] = digest({k: v for k, v in event.items() if k not in {"sha256", "source"}})
    return event


def quality_case(start=None, hours=2, signal=True):
    start = start or datetime(2026, 6, 1, 10, tzinfo=UTC)
    end, as_of = start + timedelta(hours=hours), start + timedelta(hours=hours + 1)
    inv = InverterConfig("roof", max_ac_kw=3, energy_entity_id="sensor.energy",
                         curtailed_entity_id="binary_sensor.curtailment" if signal else None)
    site = SiteConfig(50, 7, "Europe/Berlin", (StringConfig("string", "roof", 3, 30, 180),), (inv,)).to_dict()
    config = envelope("forecast_issued", {"issued_at": (start - timedelta(minutes=30)).isoformat(),
                      "site": site, "software": {"source_sha256": "a" * 64}}, 1, start - timedelta(minutes=29))
    events = [config]
    cursor = start - timedelta(minutes=5)
    while cursor < end:
        stop = cursor + timedelta(minutes=15)
        payload = {"inverter_id": "roof", "start": cursor.isoformat(), "end": stop.isoformat(),
                   "observed_at": stop.isoformat(), "energy_kwh": 0.1, "measurement_contract": MEASUREMENT_CONTRACT,
                   "continuity_id": "lineage-one", "boundary_reason": None}
        if signal:
            payload["curtailment_measurement_contract"] = "non-restored-control-v1"
        events.append(envelope("qualified_interval", payload, len(events) + 1, stop))
        cursor = stop
    binding = {"id": "roof-source-v1", "inverter_id": "roof", "statistic_id": "sensor.energy",
               "source": "test-source", "generation": config["generation"], "source_inverter_id": "roof",
               "config_event_id": config["event_id"], "config_sha256": digest(site), "producer_sha256": "a" * 64,
               "valid_from": (start - timedelta(hours=1)).isoformat(), "valid_to": (end + timedelta(minutes=30)).isoformat(),
               "measurement_kind": "native_counter", "curtailment_mode": "signal" if signal else "unconstrained",
               "qualification": {name: {"verified": True, "evidence": f"synthetic verified {name} reference",
                                         "validated_at": (end + timedelta(minutes=30)).isoformat()}
                                 for name in ("configuration", "meter", "curtailment")}}
    return events, {"schema": BINDINGS_SCHEMA, "bindings": [binding]}, [{"inverter_id": "roof", "statistic_ids": ["sensor.energy"]}], start, end, as_of


def run_case(case):
    events, bindings, mappings, start, end, as_of = case
    return build_quality(events, bindings, mappings, start=start, end=end, as_of=as_of,
                         generated_at=as_of + timedelta(minutes=15))


def reasons(report):
    return {reason for row in report["hours"] for reason in row["reasons"]}


def test_complete_cross_hour_coverage_uses_recorder_not_divided_energy():
    case = quality_case()
    original = deepcopy(case)
    report = run_case(case)
    assert case == original
    assert report["summary"]["roof"] == {"total_hours": 2, "covered_hours": 2, "qualified_hours": 2, "invalidated_hours": 0, "reasons": {}}
    assert report["quality"]["provenance"]["validated_at"] == (case[-1] + timedelta(minutes=15)).isoformat()
    assert all(set(mask) == {"inverter_id", "start", "end", "quality", "complete_coverage", "curtailed", "counter_reset"}
               for mask in report["quality"]["intervals"])
    assert all(mask["counter_reset"] is False for mask in report["quality"]["intervals"])
    assert report["energy_source"] == "unchanged_recorder_hourly_change"


@pytest.mark.parametrize("facet", ["configuration", "meter", "curtailment"])
def test_missing_qualification_retains_coverage_but_never_releases(facet):
    case = quality_case()
    case[1]["bindings"][0]["qualification"][facet] = {"verified": False, "evidence": None, "validated_at": None}
    report = run_case(case)
    assert report["summary"]["roof"]["covered_hours"] == 2
    assert report["quality"]["intervals"] == []
    assert f"{facet}_unverified" in reasons(report)


def test_one_second_gap_is_not_training_gap_tolerance():
    case = quality_case()
    event = case[0][2]
    event["payload"]["start"] = (datetime.fromisoformat(event["payload"]["start"]) + timedelta(seconds=1)).isoformat()
    rehash(event)
    report = run_case(case)
    assert report["hours"][0]["covered_seconds"] == 3599
    assert not report["hours"][0]["qualified"]
    assert report["hours"][1]["qualified"]


def test_exact_envelope_and_semantic_duplicates_are_idempotent():
    case = quality_case()
    expected = run_case(case)
    case[0].append(deepcopy(case[0][2]))
    duplicate = deepcopy(case[0][2])
    duplicate.update(event_id="copy-original-payload", sequence=999)
    case[0].append(rehash(duplicate))
    actual = run_case(case)
    assert actual["summary"] == expected["summary"]
    assert actual["quality"]["intervals"] == expected["quality"]["intervals"]


def test_conflicting_duplicate_payload_blocks_hour():
    case = quality_case()
    duplicate = deepcopy(case[0][2])
    duplicate.update(event_id="conflicting-value", sequence=999)
    duplicate["payload"]["energy_kwh"] += 0.01
    case[0].append(rehash(duplicate))
    report = run_case(case)
    assert "conflicting_interval_evidence" in reasons(report)
    assert report["summary"]["roof"]["qualified_hours"] == 1


def test_overlapping_distinct_intervals_and_lineages_block():
    case = quality_case()
    event = case[0][2]
    event["payload"]["start"] = (datetime.fromisoformat(event["payload"]["start"]) - timedelta(seconds=1)).isoformat()
    event["payload"]["end"] = (datetime.fromisoformat(event["payload"]["end"]) - timedelta(seconds=1)).isoformat()
    event["payload"]["continuity_id"] = "other-lineage"
    rehash(event)
    report = run_case(case)
    assert {"conflicting_interval_evidence", "mixed_measurement_lineage"} <= reasons(report)


@pytest.mark.parametrize("boundary", ["counter_reset", "restart_or_initial_anchor", "curtailment_invalidated", "measurement_validity_invalidated"])
def test_phase_boundary_inside_hour_blocks(boundary):
    case = quality_case()
    case[0][2]["payload"]["boundary_reason"] = boundary
    rehash(case[0][2])
    report = run_case(case)
    assert "measurement_boundary_in_hour" in report["hours"][0]["reasons"]
    assert report["hours"][1]["qualified"]


def test_boundary_before_hour_allows_crossing_quality_support():
    case = quality_case()
    case[0][1]["payload"]["boundary_reason"] = "counter_reset"
    rehash(case[0][1])
    assert run_case(case)["summary"]["roof"]["qualified_hours"] == 2


def test_late_interval_does_not_complete_old_cutoff():
    case = quality_case()
    event = case[0][2]
    event["received_at"] = (case[-1] + timedelta(minutes=1)).isoformat()
    rehash(event)
    report = run_case(case)
    assert not report["hours"][0]["qualified"]
    assert report["hours"][1]["qualified"]


def test_late_source_qualification_is_not_backdated():
    case = quality_case()
    case[1]["bindings"][0]["qualification"]["meter"]["validated_at"] = (case[-1] + timedelta(minutes=1)).isoformat()
    report = run_case(case)
    assert "meter_qualification_not_available" in reasons(report)
    assert report["quality"]["intervals"] == []


@pytest.mark.parametrize("field,value", [("measurement_contract", "old"), ("curtailment_measurement_contract", "old"), ("energy_kwh", 50)])
def test_unsupported_or_implausible_positive_event_is_not_good_coverage(field, value):
    case = quality_case()
    case[0][2]["payload"][field] = value
    rehash(case[0][2])
    assert not run_case(case)["hours"][0]["qualified"]


def test_no_signal_requires_explicit_unconstrained_qualification():
    case = quality_case(signal=False)
    assert run_case(case)["summary"]["roof"]["qualified_hours"] == 2
    case[1]["bindings"][0]["qualification"]["curtailment"]["verified"] = False
    assert run_case(case)["summary"]["roof"]["qualified_hours"] == 0


@pytest.mark.parametrize("field,value", [("statistic_id", "sensor.different"), ("producer_sha256", "b" * 64), ("config_sha256", "b" * 64), ("curtailment_mode", "unconstrained"), ("source", "foreign")])
def test_misbound_source_or_config_is_rejected(field, value):
    case = quality_case()
    case[1]["bindings"][0][field] = value
    with pytest.raises(ValueError):
        run_case(case)


def test_known_changed_config_overrides_attestation_for_period():
    case = quality_case()
    config = deepcopy(case[0][0])
    config.update(event_id="changed-config", sequence=999, received_at=case[3].isoformat())
    config["payload"]["issued_at"] = case[3].isoformat()
    config["payload"]["software"]["source_sha256"] = "b" * 64
    case[0].append(rehash(config))
    report = run_case(case)
    assert report["summary"]["roof"]["qualified_hours"] == 0
    assert "contradictory_configuration_in_binding_period" in reasons(report)


def test_missing_binding_is_visible_and_sum_of_multiple_meters_is_unsupported():
    case = quality_case()
    case[1]["bindings"] = []
    assert run_case(case)["summary"]["roof"]["qualified_hours"] == 0
    case[2][0]["statistic_ids"].append("sensor.other")
    with pytest.raises(ValueError):
        run_case(case)


def test_tampered_hash_or_conflicting_sequence_cannot_pass():
    case = quality_case()
    case[0][2]["payload"]["energy_kwh"] += 0.1
    with pytest.raises(ValueError):
        run_case(case)
    rehash(case[0][2])
    copied = deepcopy(case[0][2])
    copied["event_id"] = "collision"
    case[0].append(rehash(copied))
    with pytest.raises(ValueError):
        run_case(case)


@pytest.mark.parametrize("date,hours", [("2026-03-29", 23), ("2026-10-25", 25)])
def test_full_local_dst_days_use_real_utc_hours(date, hours):
    start = datetime.fromisoformat(date).replace(tzinfo=ZoneInfo("Europe/Berlin")).astimezone(UTC)
    case = quality_case(start, hours=hours)
    report = run_case(case)
    assert report["summary"]["roof"]["qualified_hours"] == hours
    assert len(report["quality"]["intervals"]) == hours


def test_qualification_boolean_is_not_number_and_verified_requires_reference():
    case = quality_case()
    facet = case[1]["bindings"][0]["qualification"]["meter"]
    facet["verified"] = 1
    with pytest.raises(ValueError):
        run_case(case)
    facet.update(verified=True, evidence=None)
    with pytest.raises(ValueError):
        run_case(case)


def test_other_generation_is_contradictory_evidence_not_silently_ignored():
    case = quality_case()
    event = deepcopy(case[0][2])
    event.update(event_id="foreign-generation", generation=str(UUID(int=2)))
    case[0].append(rehash(event))
    report = run_case(case)
    assert "contradictory_archive_generation" in reasons(report)
    assert not report["hours"][0]["qualified"]


def test_foreign_generation_forecast_contradicts_configuration_binding():
    case = quality_case()
    event = deepcopy(case[0][0])
    event.update(event_id="foreign-config", generation=str(UUID(int=2)))
    case[0].append(rehash(event))
    assert run_case(case)["summary"]["roof"]["qualified_hours"] == 0


def test_unknown_negative_fields_and_impossible_anchor_chronology_are_rejected():
    case = quality_case()
    case[0][2]["payload"]["curtailed"] = True
    rehash(case[0][2])
    with pytest.raises(ValueError, match="payload fields"):
        run_case(case)
    case = quality_case()
    case[0][0]["payload"]["issued_at"] = case[-1].isoformat()
    rehash(case[0][0])
    with pytest.raises(ValueError, match="chronology"):
        run_case(case)


def test_control_marker_contradicts_an_unconstrained_binding():
    case = quality_case(signal=False)
    case[0][2]["payload"]["curtailment_measurement_contract"] = "non-restored-control-v1"
    rehash(case[0][2])
    report = run_case(case)
    assert "contradictory_curtailment_configuration" in reasons(report)
    assert report["hours"][0]["mask_status"] == "invalid"


def test_known_conflict_revokes_old_positive_but_absence_does_not():
    from scripts.capture_actuals import CaptureError, actual_records_from_captures, normalize_capture
    from tests.test_capture_actuals import capture

    case = quality_case()
    raw = capture(start=case[3], end=case[4], received=case[-1])
    # The capture fixture has the same exact 1:1 mapping as quality_case.
    good = run_case(case)
    first = normalize_capture(raw, good["quality"], normalized_at=case[-1] + timedelta(minutes=15))
    assert len(actual_records_from_captures([first])) == 2
    bad_case = deepcopy(case)
    duplicate = deepcopy(bad_case[0][2])
    duplicate.update(event_id="conflicting-value", sequence=999)
    duplicate["payload"]["energy_kwh"] += 0.01
    bad_case[0].append(rehash(duplicate))
    later = case[-1] + timedelta(minutes=30)
    report = build_quality(*bad_case[:3], start=case[3], end=case[4], as_of=case[-1], generated_at=later)
    second = normalize_capture(raw, report["quality"], normalized_at=later)
    with pytest.raises(CaptureError, match="later invalid actual revision"):
        actual_records_from_captures([first, second])
    assert len(actual_records_from_captures([first, second], as_of=case[-1] + timedelta(minutes=20))) == 2
    # Just a smaller incomplete input export must not annul an earlier hour.
    case[0].pop(2)
    missing = build_quality(*case[:3], start=case[3], end=case[4], as_of=case[-1], generated_at=later)
    third = normalize_capture(raw, missing["quality"], normalized_at=later)
    assert len(actual_records_from_captures([first, third])) == 2


def test_unverified_binding_cannot_invalidate_an_existing_external_scope():
    case = quality_case()
    case[0][2]["payload"]["boundary_reason"] = "counter_reset"
    rehash(case[0][2])
    case[1]["bindings"][0]["qualification"]["configuration"]["verified"] = False
    report = run_case(case)
    assert report["quality"]["intervals"] == []
    assert report["summary"]["roof"]["invalidated_hours"] == 0


@pytest.mark.parametrize("gap_microseconds", [0, 1])
def test_many_fractional_second_reports_preserve_exact_time_coverage(gap_microseconds):
    case = quality_case()
    events, _, _, start, end, _ = case
    prototype = deepcopy(events[1]["payload"])
    events[:] = events[:1]
    cursor = start
    while cursor < end:
        stop = min(end, cursor + timedelta(seconds=13, microseconds=123457))
        payload = {**prototype, "start": cursor.isoformat(), "end": stop.isoformat(),
                   "observed_at": stop.isoformat(), "energy_kwh": 0}
        events.append(envelope("qualified_interval", payload, len(events) + 1, stop))
        cursor = stop
    if gap_microseconds:
        payload = events[2]["payload"]
        payload["start"] = (datetime.fromisoformat(payload["start"]) + timedelta(microseconds=gap_microseconds)).isoformat()
        rehash(events[2])
    report = run_case(case)
    assert report["summary"]["roof"]["covered_hours"] == 2 - bool(gap_microseconds)
    assert report["hours"][0]["covered_seconds"] == 3600 - gap_microseconds / 1_000_000
