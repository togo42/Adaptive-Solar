"""Measured support and conservative original-forecast integration.

The gap allowance qualifies a set of disjoint measured pieces. It never adds
energy or elapsed seconds to that support. Opaque old rows remain exact-only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from bisect import bisect_left
import math

from ..const import (MAX_MEASUREMENT_GAP_SECONDS_PER_HOUR,
                     MAX_MEASUREMENT_SINGLE_GAP_SECONDS, MEASUREMENT_CONTRACT,
                     MAX_MEASUREMENT_PARTS_PER_ROW)
from .models import utc_time


@dataclass(frozen=True)
class MeasuredBlock:
    start: datetime
    end: datetime
    energy: float
    observed: datetime
    support: tuple[tuple[datetime, datetime], ...]
    lineage: str | None = None
    gap_seconds: float = 0.0

    @property
    def duration(self):
        return sum((b - a).total_seconds() for a, b in self.support)


def continuity(row):
    if row.get("measurement_contract") != MEASUREMENT_CONTRACT:
        return None
    value = row.get("continuity_id")
    return value if isinstance(value, str) and value else None


def expand_interval(row, *, cap_w=None):
    """Recover only genuine recorded delta endpoints from a coalesced row."""
    parts = row.get("measurement_parts")
    if parts is None:
        return [row]
    if (continuity(row) is None or not isinstance(parts, (list, tuple))
            or not 1 <= len(parts) <= MAX_MEASUREMENT_PARTS_PER_ROW):
        raise ValueError("invalid original measurement parts")
    declared = row.get("energy_kwh")
    if isinstance(declared, bool) or not isinstance(declared, (int, float)) or not math.isfinite(declared) or declared < 0:
        raise ValueError("invalid coalesced measurement energy")
    previous = utc_time(datetime.fromisoformat(row["start"]))
    observed, total, result = None, 0.0, []
    metadata = {key: value for key, value in row.items() if key != "measurement_parts"}
    for index, part in enumerate(parts):
        if not isinstance(part, (list, tuple)) or len(part) != 4:
            raise ValueError("invalid original measurement part")
        start, end, receipt = (utc_time(datetime.fromisoformat(value)) for value in part[:3])
        energy = part[3]
        duration = (end - start).total_seconds()
        if (start != previous or not 0 < duration <= 3600 or receipt < end
                or isinstance(energy, bool) or not isinstance(energy, (float, int)) or not math.isfinite(energy)
                or energy < 0 or cap_w is not None and energy > cap_w * 1.1 * duration / 3600000):
            raise ValueError("invalid original measurement part timing/energy")
        result.append({**metadata, "start": start.isoformat(), "end": end.isoformat(),
                       "observed_at": receipt.isoformat(), "energy_kwh": energy,
                       "boundary_reason": row.get("boundary_reason") if index == 0 else None})
        previous, observed, total = end, max(observed, receipt) if observed is not None else receipt, total + energy
    if (previous != utc_time(datetime.fromisoformat(row["end"]))
            or observed != utc_time(datetime.fromisoformat(row["observed_at"]))
            or not math.isclose(total, row["energy_kwh"], rel_tol=1e-9, abs_tol=1e-9)):
        raise ValueError("original measurement parts do not match the coalesced row")
    return result


def can_follow(block, start, lineage, *, budget_seconds=MAX_MEASUREMENT_GAP_SECONDS_PER_HOUR):
    gap = (start - block.end).total_seconds()
    if gap == 0:
        # Explicitly different monitored phases must never be rejoined, even
        # when timestamp rounding makes their boundary appear identical.
        return block.lineage == lineage
    return (0 < gap <= MAX_MEASUREMENT_SINGLE_GAP_SECONDS
            and lineage is not None and lineage == block.lineage
            and block.gap_seconds + gap <= budget_seconds)


class _SpanIndex:
    """Existence of a half-open overlap in O(log n), including left crossings."""

    def __init__(self, spans):
        self.starts, self.prefix_ends = [], []
        maximum = None
        for start, end in sorted(spans):
            maximum = max(maximum, end) if maximum is not None else end
            self.starts.append(start)
            self.prefix_ends.append(maximum)

    def overlaps(self, start, end):
        position = bisect_left(self.starts, end) - 1
        return position >= 0 and self.prefix_ends[position] > start


class MeasurementIndex:
    """One availability-filtered interval/conflict index per inverter and join.

    Deduplication and the prefix-end sweep see every available interval before
    target clipping. Their overlap regions therefore also protect target edges,
    while future receipts and conflicts outside a target cannot invalidate it.
    """

    def __init__(self, measured, as_of):
        available, conflicts, unfinalized, future = {}, [], [], []
        for start, end, row in measured:
            observed = utc_time(datetime.fromisoformat(row["observed_at"]))
            if observed < end:
                unfinalized.append((start, end))
                continue
            if as_of is not None and observed > as_of:
                future.append((start, end))
                continue
            signature = (row["energy_kwh"], row.get("curtailment_measurement_contract"),
                         continuity(row), row.get("boundary_reason"))
            previous = available.get((start, end))
            if previous is not None:
                if previous[0] != signature:
                    conflicts.append((start, end))
                if previous[1] <= observed:
                    continue
            available[start, end] = signature, observed, row
        self.rows = [(start, end, row) for (start, end), (_, _, row) in sorted(available.items())]
        self.starts = [start for start, _, _ in self.rows]
        self.prefix_ends = []
        maximum = None
        for start, end, _ in self.rows:
            if maximum is not None and start < maximum:
                conflicts.append((start, min(end, maximum)))
            maximum = max(maximum, end) if maximum is not None else end
            self.prefix_ends.append(maximum)
        self.conflicts = _SpanIndex(conflicts)
        self.unfinalized = _SpanIndex(unfinalized)
        self.future = _SpanIndex(future)


def blocks(index, a, b):
    """Check all available intersections before choosing whole contained parts."""
    if index.conflicts.overlaps(a, b):
        return [], {"overlapping_measurements"}
    reasons = set()
    if index.unfinalized.overlaps(a, b):
        reasons.add("no_finalized_measurements")
    if index.future.overlaps(a, b):
        reasons.add("observation_not_yet_available")
    first, stop = bisect_left(index.starts, a), bisect_left(index.starts, b)
    if first and index.prefix_ends[first - 1] > a:
        reasons.add("measurement_crosses_target_boundary")
    result = []
    for position in range(first, stop):
        start, end, row = index.rows[position]
        if end > b:
            reasons.add("measurement_crosses_target_boundary")
            continue
        energy, observed = row["energy_kwh"], utc_time(datetime.fromisoformat(row["observed_at"]))
        lineage, boundary = continuity(row), row.get("boundary_reason")
        if (result and boundary is None and can_follow(result[-1], start, lineage,
                budget_seconds=MAX_MEASUREMENT_GAP_SECONDS_PER_HOUR * (b - a).total_seconds() / 3600)):
            previous = result.pop()
            gap = (start - previous.end).total_seconds()
            support = previous.support
            if gap == 0:
                support = (*support[:-1], (support[-1][0], end))
            else:
                support = (*support, (start, end))
            result.append(MeasuredBlock(previous.start, end, previous.energy + energy,
                                        max(previous.observed, observed), support, lineage,
                                        previous.gap_seconds + gap))
        else:
            if result:
                reasons.add("internal_measurement_gap")
            result.append(MeasuredBlock(start, end, energy, observed, ((start, end),), lineage))
    return result, reasons or (set() if result else {"no_whole_measurement_inside_target"})


def integrate_original(rows, support):
    """Integrate archived cell means/features over measured support only.

    Caller groups a genuine common issue and checks prospective provenance.
    Overlapping/conflicting source cells, incompatible feature schemas and
    missing forecast coverage fail closed; source energy is never measured.
    """
    unique = {}
    for row in rows:
        key = row["start"], row["end"]
        if key in unique and unique[key] != row:
            return None
        unique[key] = row
    cells = sorted((utc_time(datetime.fromisoformat(row["start"])),
                    utc_time(datetime.fromisoformat(row["end"])), row) for row in unique.values())
    used, schema, total = [], None, 0.0
    for a, b in support:
        cursor = a
        for start, end, row in cells:
            if end <= a or start >= b:
                continue
            left, right = max(start, a), min(end, b)
            if left != cursor or right <= left:
                return None
            features = row["features"]
            if schema is None:
                schema = set(features)
            if set(features) != schema or any(isinstance(v, bool) or not isinstance(v, (float, int))
                                               or not math.isfinite(v) for v in features.values()):
                return None
            seconds = (right - left).total_seconds()
            used.append((seconds, row))
            total += seconds
            cursor = right
        if cursor != b:
            return None
    if not total:
        return None
    features = {key: sum(seconds * row["features"][key] for seconds, row in used) / total for key in schema}
    baseline = sum(seconds * row["baseline_w"] for seconds, row in used) / total
    features["baseline_w"] = baseline
    return baseline, features
