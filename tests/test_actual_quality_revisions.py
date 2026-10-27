"""Whole-hour releases and overlapping negative evidence keep separate revisions."""
from copy import deepcopy
from datetime import timedelta
from itertools import permutations

import pytest

from scripts import capture_actuals as actuals
from tests.test_capture_actuals import START, capture, mask

STOP = START + timedelta(hours=1)
GOOD_RECEIPT = STOP + timedelta(hours=1)
BAD_REVISION = STOP + timedelta(hours=2)


def normalized(quality, received=GOOD_RECEIPT, *, start=START, end=STOP):
    raw = capture(start=start, end=end, received=received)
    validated = actuals.utc(quality["provenance"]["validated_at"])
    return actuals.normalize_capture(raw, quality, normalized_at=max(received, validated))


def positive(revision=STOP + timedelta(minutes=30), received=GOOD_RECEIPT):
    quality = mask(start=START, end=STOP)
    quality["provenance"]["validated_at"] = revision.isoformat()
    return normalized(quality, received)


def partial(revision=BAD_REVISION, received=GOOD_RECEIPT + timedelta(minutes=30), **flags):
    quality = mask(start=START + timedelta(minutes=15), end=START + timedelta(minutes=30), **flags)
    quality["provenance"]["validated_at"] = revision.isoformat()
    return normalized(quality, received)


@pytest.mark.parametrize("flags,reason", [({"curtailed": True}, "curtailed"),
    ({"counter_reset": True}, "counter_reset"), ({"quality": "invalid"}, "unverified_measurement_coverage"),
    ({"complete_coverage": False}, "unverified_measurement_coverage"),
    ({"quality": "unknown"}, "unverified_measurement_coverage"),
    ({"curtailed": None}, "unknown_curtailment"), ({"counter_reset": None}, "unknown_counter_reset")])
@pytest.mark.parametrize("reverse", [False, True])
def test_partial_negative_evidence_invalidates_an_older_whole_hour_only_when_available(flags, reason, reverse):
    old, negative = positive(), partial(**flags)
    exclusion = negative["normalization"]["excluded"][0]
    assert exclusion["start"] == START.isoformat() and exclusion["end"] == STOP.isoformat()
    assert reason in exclusion["reasons"] and "missing_quality_evidence" in exclusion["reasons"]
    assert negative["normalization"]["records"] == []
    sequence = [negative, old] if reverse else [old, negative]
    assert len(actuals.actual_records_from_captures(sequence, as_of=BAD_REVISION - timedelta(microseconds=1))) == 1
    for cutoff in (BAD_REVISION, None):
        with pytest.raises(actuals.CaptureError, match="later invalid actual revision"):
            actuals.actual_records_from_captures(sequence, as_of=cutoff)


def test_partial_positive_evidence_cannot_release_or_advance_quality_revision():
    clear = partial()
    assert clear["normalization"]["records"] == []
    assert clear["normalization"]["excluded"][0]["reasons"] == ["missing_quality_evidence"]
    old, negative = positive(), partial(revision=BAD_REVISION - timedelta(minutes=10), curtailed=True)
    for sequence in permutations([old, negative, clear]):
        with pytest.raises(actuals.CaptureError, match="later invalid actual revision"):
            actuals.actual_records_from_captures(sequence)


@pytest.mark.parametrize("start,end,invalidates", [(-15, 0, False), (60, 75, False),
                                                   (-15, 1, True), (59, 75, True)])
def test_negative_quality_uses_half_open_overlap_not_boundary_contact(start, end, invalidates):
    quality = mask(start=START + timedelta(minutes=start), end=START + timedelta(minutes=end), curtailed=True)
    quality["provenance"]["validated_at"] = BAD_REVISION.isoformat()
    negative = normalized(quality)
    reasons = negative["normalization"]["excluded"][0]["reasons"]
    assert ("curtailed" in reasons) is invalidates
    if invalidates:
        with pytest.raises(actuals.CaptureError, match="later invalid actual revision"):
            actuals.actual_records_from_captures([positive(), negative])
    else:
        assert len(actuals.actual_records_from_captures([positive(), negative])) == 1


def test_raw_reread_with_old_positive_mask_cannot_override_new_partial_negative():
    old = positive()
    negative = partial(curtailed=True)
    reread = positive(received=BAD_REVISION + timedelta(hours=1))
    for sequence in permutations([old, negative, reread]):
        with pytest.raises(actuals.CaptureError, match="later invalid actual revision"):
            actuals.actual_records_from_captures(sequence)


def test_new_whole_hour_positive_revision_can_requalify_after_partial_negative():
    old, negative = positive(), partial(counter_reset=True)
    revision = BAD_REVISION + timedelta(hours=1)
    requalified = positive(revision=revision)
    for sequence in permutations([old, negative, requalified]):
        with pytest.raises(actuals.CaptureError, match="later invalid actual revision"):
            actuals.actual_records_from_captures(sequence, as_of=revision - timedelta(microseconds=1))
        rows = actuals.actual_records_from_captures(sequence, as_of=revision)
        assert len(rows) == 1 and rows[0]["observed_at"] == revision.isoformat()


def test_later_received_older_negative_quality_does_not_undo_newer_full_positive_revision():
    newer_positive = positive(revision=BAD_REVISION + timedelta(hours=1))
    stale_negative = partial(revision=BAD_REVISION, received=BAD_REVISION + timedelta(hours=2), curtailed=True)
    for sequence in ([stale_negative, newer_positive], [newer_positive, stale_negative]):
        rows = actuals.actual_records_from_captures(sequence)
        assert len(rows) == 1
        assert rows[0]["observed_at"] == (BAD_REVISION + timedelta(hours=1)).isoformat()


def test_equal_quality_revision_fails_closed_and_a_later_negative_can_revoke_requalification():
    tied_positive, tied_negative = positive(revision=BAD_REVISION), partial(curtailed=True)
    for sequence in ([tied_positive, tied_negative], [tied_negative, tied_positive]):
        with pytest.raises(actuals.CaptureError, match="later invalid actual revision"):
            actuals.actual_records_from_captures(sequence)
    requalified = positive(revision=BAD_REVISION + timedelta(hours=1))
    latest = partial(revision=BAD_REVISION + timedelta(hours=2), quality="invalid")
    for sequence in permutations([tied_negative, requalified, latest]):
        assert len(actuals.actual_records_from_captures(sequence, as_of=BAD_REVISION + timedelta(hours=1))) == 1
        with pytest.raises(actuals.CaptureError, match="later invalid actual revision"):
            actuals.actual_records_from_captures(sequence, as_of=BAD_REVISION + timedelta(hours=2))


def test_negative_availability_waits_for_raw_receipt_even_if_quality_is_older():
    received = BAD_REVISION + timedelta(hours=1)
    negative = partial(revision=BAD_REVISION, received=received, quality="invalid")
    assert len(actuals.actual_records_from_captures([positive(), negative], as_of=received - timedelta(microseconds=1))) == 1
    with pytest.raises(actuals.CaptureError, match="later invalid actual revision"):
        actuals.actual_records_from_captures([positive(), negative], as_of=received)


@pytest.mark.parametrize("other_scope", [False, True])
def test_negative_mask_applies_to_previously_accepted_hours_outside_current_raw_query(other_scope):
    quality = mask(start=START + timedelta(minutes=15), end=START + timedelta(minutes=30), curtailed=True)
    quality["provenance"]["validated_at"] = BAD_REVISION.isoformat()
    raw = capture(start=STOP, end=STOP + timedelta(hours=1), received=BAD_REVISION)
    if other_scope:
        raw["raw"]["mappings"][0]["inverter_id"] = "different_scope"
    later = actuals.normalize_capture(raw, quality, normalized_at=BAD_REVISION)
    assert all("curtailed" not in row["reasons"] for row in later["normalization"]["excluded"])
    for sequence in ([positive(), later], [later, positive()]):
        assert len(actuals.actual_records_from_captures(sequence, as_of=BAD_REVISION - timedelta(microseconds=1))) == 1
        with pytest.raises(actuals.CaptureError, match="later invalid actual revision"):
            actuals.actual_records_from_captures(sequence, as_of=BAD_REVISION)


def test_negative_mask_for_unknown_scope_creates_no_label_and_does_not_invalidate_other_scope():
    negative = partial(curtailed=True)
    quality = deepcopy(negative["quality"])
    quality["intervals"][0]["inverter_id"] = "unknown_scope"
    negative = normalized(quality)
    rows = actuals.actual_records_from_captures([positive(), negative])
    assert len(rows) == 1 and rows[0]["inverter_id"] == "roof"


def test_old_partial_negative_normalization_requires_explicit_regeneration_from_original_evidence():
    old = positive()
    negative = partial(curtailed=True)
    legacy = deepcopy(negative)
    legacy["normalization"]["excluded"][0]["reasons"] = ["missing_quality_evidence"]
    original = deepcopy(legacy)
    for cutoff in (BAD_REVISION - timedelta(microseconds=1), None):
        with pytest.raises(actuals.CaptureError, match="differ from raw capture and quality evidence"):
            actuals.actual_records_from_captures([old, legacy], as_of=cutoff)
    assert legacy == original  # No implicit mutation of the append-only source.
    regenerated_at = BAD_REVISION + timedelta(hours=1)
    regenerated = actuals.normalize_capture(legacy, legacy["quality"], normalized_at=regenerated_at)
    assert regenerated["normalized_at"] == regenerated_at.isoformat()
    assert regenerated["retrieved_at"] == legacy["retrieved_at"]
    assert regenerated["quality"] == legacy["quality"]
    assert len(actuals.actual_records_from_captures([old, regenerated], as_of=BAD_REVISION - timedelta(microseconds=1))) == 1
    with pytest.raises(actuals.CaptureError, match="later invalid actual revision"):
        actuals.actual_records_from_captures([old, regenerated])
    assert actuals.actual_records_from_captures([old])[0] == old["normalization"]["records"][0]
