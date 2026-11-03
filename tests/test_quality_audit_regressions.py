"""Causal input filtering and binding-wide revocation across capture windows."""
from copy import deepcopy
from datetime import timedelta

from freezegun import freeze_time
import pytest

from custom_components.adaptive_solar.core.actual_quality import CONTINUOUS_BINDINGS_SCHEMA, build_quality
from scripts import capture_actuals, continuous_quality
from tests.test_actual_quality import quality_case, rehash, run_case
from tests.test_capture_actuals import capture
from tests.test_continuous_quality import _OriginalEvents, continuous_case


def extra_interval(case, defect, placement):
    event = deepcopy(case[0][2])
    event.update(sequence=999, event_id="audit-interval")
    payload = event["payload"]
    start = {"before_target": case[3] - timedelta(minutes=30),
             "after_target": case[4] + timedelta(minutes=1),
             "outside_binding": case[3] - timedelta(days=2)}.get(placement)
    if start is not None:
        end = start + timedelta(minutes=15)
        payload.update(start=start.isoformat(), end=end.isoformat(), observed_at=end.isoformat())
        event["received_at"] = max(end, case[-1]).isoformat()
    elif placement == "future":
        event["received_at"] = (case[-1] + timedelta(seconds=1)).isoformat()
    elif placement == "foreign_source":
        event["source"] = "different-source"
    elif placement == "foreign_inverter":
        payload["inverter_id"] = "different-inverter"
    if defect == "overlong":
        payload["start"] = (capture_actuals.utc(payload["end"]) - timedelta(seconds=901)).isoformat()
    elif defect == "negative_energy":
        payload["energy_kwh"] = -1
    elif defect == "backwards":
        payload["start"] = payload["end"]
    elif defect == "extra_field":
        payload["unexpected"] = "synthetic"
    return rehash(event)


@pytest.mark.parametrize("defect", ["overlong", "negative_energy", "backwards", "extra_field"])
@pytest.mark.parametrize("placement", ["future", "before_target", "after_target", "outside_binding", "foreign_source", "foreign_inverter"])
def test_unavailable_or_unrelated_semantic_payload_does_not_abort_qualification(defect, placement):
    case = quality_case()
    before = run_case(case)
    original = deepcopy(case[0])
    case[0].append(extra_interval(case, defect, placement))
    actual = run_case(case)
    assert actual["hours"] == before["hours"]
    assert actual["quality"]["intervals"] == before["quality"]["intervals"]
    # Offline provenance still binds the complete supplied original input.
    assert actual["event_set_sha256"] != before["event_set_sha256"]
    assert case[0][:-1] == original


@pytest.mark.parametrize("defect", ["overlong", "negative_energy", "backwards", "extra_field"])
def test_relevant_semantic_contract_violations_remain_hard_errors(defect):
    case = quality_case()
    case[0].append(extra_interval(case, defect, "relevant"))
    with pytest.raises(ValueError):
        run_case(case)


def test_late_invalid_interval_is_checked_exactly_when_its_receipt_becomes_available():
    case = quality_case()
    event = extra_interval(case, "overlong", "future")
    case[0].append(event)
    assert run_case(case)["summary"]["roof"]["qualified_hours"] == 2
    with pytest.raises(ValueError, match="bounded meter delta"):
        build_quality(*case[:3], start=case[3], end=case[4], as_of=capture_actuals.utc(event["received_at"]),
                      generated_at=capture_actuals.utc(event["received_at"]))


def test_future_original_integrity_error_is_not_hidden_by_semantic_filtering():
    case = quality_case()
    event = extra_interval(case, "overlong", "future")
    event["payload"]["energy_kwh"] = 2
    case[0].append(event)
    with pytest.raises(ValueError, match="checksum"):
        run_case(case)


def contradictory_configuration(case, kind="producer"):
    event = deepcopy(case[0][0])
    stamp = case[3] + timedelta(hours=1)
    event.update(event_id="changed-configuration", sequence=998, received_at=stamp.isoformat())
    event["payload"]["issued_at"] = stamp.isoformat()
    if kind == "producer":
        event["payload"]["software"]["source_sha256"] = "b" * 64
    elif kind == "configuration":
        event["payload"]["site"]["latitude"] += 1
    else:
        event["generation"] = "00000000-0000-0000-0000-000000000002"
    return rehash(event)


@pytest.mark.parametrize("kind", ["producer", "configuration", "generation"])
@pytest.mark.parametrize("reverse", [False, True])
def test_configuration_conflict_revokes_disjoint_old_capture_at_its_real_validation_time(kind, reverse):
    case = quality_case(hours=4)
    positive = run_case(case)
    early_raw = capture(start=case[3], end=case[3] + timedelta(hours=1), received=case[-1])
    old = capture_actuals.normalize_capture(early_raw, positive["quality"], normalized_at=positive["generated_at"])
    case[0].append(contradictory_configuration(case, kind))
    now = case[-1] + timedelta(hours=1)
    recent_start = case[4] - timedelta(hours=1)
    later = build_quality(*case[:3], start=recent_start, end=case[4], as_of=now, generated_at=now)
    recent_raw = capture(start=recent_start, end=case[4], received=now)
    new = capture_actuals.normalize_capture(recent_raw, later["quality"], normalized_at=now)
    mask, = later["quality"]["intervals"]
    assert mask["quality"] == "invalid"
    assert mask["start"] == case[1]["bindings"][0]["valid_from"]
    assert mask["end"] == case[4].isoformat()
    assert later["binding_checks"][0]["invalidated_period"] == {"start": mask["start"], "end": mask["end"]}
    assert len(later["hours"]) == 1
    assert len(capture_actuals.actual_records_from_captures([old, new], as_of=now - timedelta(microseconds=1))) == 1
    captures = [new, old] if reverse else [old, new]
    with pytest.raises(capture_actuals.CaptureError, match="later invalid actual revision"):
        capture_actuals.actual_records_from_captures(captures, as_of=now)


def test_period_revocation_needs_verified_available_configuration_binding():
    case = quality_case()
    case[0].append(contradictory_configuration(case))
    for facet in ({"verified": False, "evidence": None, "validated_at": None},
                  {"verified": True, "evidence": "later source check", "validated_at": (case[-1] + timedelta(seconds=1)).isoformat()}):
        case[1]["bindings"][0]["qualification"]["configuration"] = facet
        report = run_case(case)
        assert report["quality"]["intervals"] == []
        assert "invalidated_period" not in report["binding_checks"][0]


def test_period_revocation_is_compact_and_excludes_partial_and_future_hours():
    case = continuous_case()
    binding = case[1]["bindings"][0]
    binding["valid_from"] = (case[3] - timedelta(minutes=45)).isoformat()
    case[0].append(contradictory_configuration(case))
    cutoff = case[4] - timedelta(minutes=20)
    report = build_quality(*case[:3], start=case[3], end=case[4], as_of=cutoff, generated_at=cutoff)
    mask, = report["quality"]["intervals"]
    assert mask["start"] == case[3].isoformat()
    assert mask["end"] == (case[4] - timedelta(hours=1)).isoformat()
    binding["valid_from"] = "2000-01-01T00:00:00+00:00"
    binding["valid_to"] = "2100-01-01T00:00:00+00:00"
    assert case[1]["schema"] == CONTINUOUS_BINDINGS_SCHEMA
    report = run_case(case)
    assert len(report["quality"]["intervals"]) == 1
    assert report["quality"]["intervals"][0]["end"] == case[-1].isoformat()


def test_continuous_source_projection_propagates_period_mask_to_disjoint_capture():
    case = continuous_case()
    early_end = case[3] + timedelta(hours=1)
    early_raw = capture(start=case[3], end=early_end, received=case[-1])
    with freeze_time(case[-1]):
        old = continuous_quality.derive(_OriginalEvents(case[0]), early_raw, case[1])
    case[0].append(contradictory_configuration(case))
    later = case[-1] + timedelta(hours=1)
    recent_raw = capture(start=early_end, end=case[4], received=later)
    with freeze_time(later):
        new = continuous_quality.derive(_OriginalEvents(case[0]), recent_raw, case[1])
    assert new["raw"] == recent_raw["raw"]
    assert new["retrieved_at"] == recent_raw["retrieved_at"]
    assert len(new["quality"]["intervals"]) == 1
    assert new["quality_derivation"]["event_set_hash_format"] == "original-envelope-reference-manifest-v1"
    with pytest.raises(capture_actuals.CaptureError, match="later invalid actual revision"):
        capture_actuals.actual_records_from_captures([old, new])
