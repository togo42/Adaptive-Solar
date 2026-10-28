"""Explicit Recorder predecessor contradictions retain their raw receipt axis."""
from copy import deepcopy
from datetime import timedelta
from itertools import permutations

import pytest

from scripts import capture_actuals as actuals
from tests.test_actual_quality_revisions import BAD_REVISION, GOOD_RECEIPT, STOP, positive
from tests.test_capture_actuals import capture


def predecessor(value=1, *, received=BAD_REVISION, missing=False, absent_change=False):
    raw = capture(start=STOP, end=STOP + timedelta(hours=1), received=received)
    rows = raw["raw"]["statistics"]["sensor.energy"]
    if missing:
        rows.pop(0)
    elif absent_change:
        rows[0].pop("change")
    else:
        rows[0]["change"] = value
    # No positive quality is asserted for either the predecessor or target.
    return actuals.normalize_capture(raw, quality=None, normalized_at=received)


@pytest.mark.parametrize("value,absent_change", [(None, False), (-1, False), (True, False),
                                                (float("nan"), False), (float("inf"), False), (1, True)])
@pytest.mark.parametrize("reverse", [False, True])
def test_explicit_invalid_predecessor_revokes_prior_hour_at_its_own_receipt(value, absent_change, reverse):
    old, invalid = positive(), predecessor(value, absent_change=absent_change)
    assert invalid["normalization"]["records"] == []
    assert all(row["start"] == STOP.isoformat() for row in invalid["normalization"]["excluded"])
    sequence = [invalid, old] if reverse else [old, invalid]
    assert len(actuals.actual_records_from_captures(sequence, as_of=BAD_REVISION - timedelta(microseconds=1))) == 1
    with pytest.raises(actuals.CaptureError, match="later invalid actual revision"):
        actuals.actual_records_from_captures(sequence, as_of=BAD_REVISION)


@pytest.mark.parametrize("missing", ["row", "series"])
def test_missing_predecessor_is_absence_not_negative_evidence(missing):
    raw = predecessor(missing=True)
    if missing == "series":
        raw["raw"]["statistics"]["sensor.energy"] = None
        raw = actuals.normalize_capture(raw, quality=None, normalized_at=raw["normalized_at"])
    rows = actuals.actual_records_from_captures([positive(), raw])
    assert len(rows) == 1 and rows[0]["observed_at"] == GOOD_RECEIPT.isoformat()


@pytest.mark.parametrize("value", [None, 2])
def test_later_qualified_target_revision_restores_after_invalid_or_changed_predecessor(value):
    old, invalid = positive(), predecessor(value)
    recovered_at = BAD_REVISION + timedelta(hours=1)
    recovered = positive(received=recovered_at)
    for sequence in permutations([old, invalid, recovered]):
        with pytest.raises(actuals.CaptureError, match="later invalid actual revision"):
            actuals.actual_records_from_captures(sequence, as_of=recovered_at - timedelta(microseconds=1))
        rows = actuals.actual_records_from_captures(sequence, as_of=recovered_at)
        assert len(rows) == 1 and rows[0]["observed_at"] == recovered_at.isoformat()


@pytest.mark.parametrize("reverse", [False, True])
def test_valid_changed_predecessor_is_an_explicit_raw_revision_conflict(reverse):
    old, changed = positive(), predecessor(2)
    sequence = [changed, old] if reverse else [old, changed]
    assert len(actuals.actual_records_from_captures(sequence, as_of=BAD_REVISION - timedelta(microseconds=1))) == 1
    with pytest.raises(actuals.CaptureError, match="later invalid actual revision"):
        actuals.actual_records_from_captures(sequence, as_of=BAD_REVISION)


def test_older_changed_predecessor_cannot_override_newer_qualified_target():
    changed = predecessor(2, received=BAD_REVISION)
    newer = positive(received=BAD_REVISION + timedelta(hours=1))
    for sequence in ([changed, newer], [newer, changed]):
        assert actuals.actual_records_from_captures(sequence) == newer["normalization"]["records"]


def test_same_predecessor_cannot_create_or_requalify_a_positive_label():
    same = predecessor(1, received=BAD_REVISION + timedelta(hours=1))
    assert actuals.actual_records_from_captures([same]) == []
    old = positive()
    assert actuals.actual_records_from_captures([old, same])[0]["observed_at"] == GOOD_RECEIPT.isoformat()
    invalid = predecessor(None)
    for sequence in permutations([old, invalid, same]):
        with pytest.raises(actuals.CaptureError, match="later invalid actual revision"):
            actuals.actual_records_from_captures(sequence)


@pytest.mark.parametrize("mode", ["complete_changed", "incomplete", "bad_metadata", "partial_invalid"])
def test_predecessor_aggregate_requires_all_members_for_positive_value_comparison(mode):
    revised = predecessor(1)
    raw = revised["raw"]
    template = raw["statistics"].pop("sensor.energy")
    raw["statistics"] = {"sensor.a": deepcopy(template), "sensor.b": deepcopy(template)}
    raw["mappings"][0]["statistic_ids"] = ["sensor.a", "sensor.b"]
    raw["request"]["statistic_ids"] = ["sensor.a", "sensor.b"]
    raw["metadata"] = [{**raw["metadata"][0], "statistic_id": statistic} for statistic in ("sensor.a", "sensor.b")]
    if mode in {"incomplete", "partial_invalid"}:
        raw["statistics"]["sensor.b"].pop(0)
    if mode == "bad_metadata":
        raw["metadata"][1]["has_sum"] = False
    if mode == "partial_invalid":
        raw["statistics"]["sensor.a"][0]["change"] = None
    revised = actuals.normalize_capture(revised, quality=None, normalized_at=revised["normalized_at"])
    if mode in {"complete_changed", "partial_invalid"}:
        with pytest.raises(actuals.CaptureError, match="later invalid actual revision"):
            actuals.actual_records_from_captures([positive(), revised])
    else:
        assert len(actuals.actual_records_from_captures([positive(), revised])) == 1


def test_correct_aggregate_predecessor_does_not_compare_individual_counter_as_total():
    revised = predecessor(0.5)
    raw = revised["raw"]
    raw["statistics"]["sensor.second"] = deepcopy(raw["statistics"]["sensor.energy"])
    raw["mappings"][0]["statistic_ids"].append("sensor.second")
    raw["request"]["statistic_ids"].append("sensor.second")
    raw["metadata"].append({**raw["metadata"][0], "statistic_id": "sensor.second"})
    revised = actuals.normalize_capture(revised, quality=None, normalized_at=revised["normalized_at"])
    rows = actuals.actual_records_from_captures([positive(), revised])
    assert len(rows) == 1 and rows[0]["power_w"] == 1000
