"""Bounded prospective comparison captures, independent of ML training."""
from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
import math
from zoneinfo import ZoneInfo

from .models import ForecastPoint, utc_time

COMPARISON_ARCHIVE_KEY = "comparison_archive_v1"
MAX_COMPARISON_POINTS = 250000
MAX_COMPARISON_SNAPSHOTS = 1024
COMPARISON_RETENTION_DAYS = 120
POINT_COLUMNS = ("inverter_id", "start", "end", "original_start", "power_w", "baseline_w")


def _stamp(text):
    if not isinstance(text, str):
        raise ValueError("comparison timestamp must be an ISO string")
    return utc_time(datetime.fromisoformat(text))


def _fingerprint(value, lengths=(16, 64)):
    return (isinstance(value, str) and len(value) in lengths
            and all(char in "0123456789abcdef" for char in value))


class ComparisonArchive:
    """First actual local capture per source/day after18:00; whole snapshots retained.

    Original weather issues never substitute for local availability. Point
    means may be cropped to future support without creating measured energy.
    Row and snapshot caps are hard bounds, not a120-day retention guarantee.
    """

    def __init__(self, fingerprint, history_fingerprint, output_caps, timezone_name="UTC"):
        self.fingerprint = fingerprint
        self.history_fingerprint = history_fingerprint
        self.output_caps = dict(output_caps)
        self.zone = ZoneInfo(timezone_name)
        self.snapshots = []
        self.restore_status = "empty"
        self.revision = 0

    def capture(self, arms, *, calculated_at, received_at, weather_issues):
        calculated_at, received_at = utc_time(calculated_at), utc_time(received_at)
        if received_at < calculated_at or received_at > datetime.now(UTC):
            raise ValueError("comparison receipt predates calculation")
        local = received_at.astimezone(self.zone)
        if local.hour < 18:
            return False
        known = {(row["source"], _stamp(row["retrieved_at"]).astimezone(self.zone).date())
                 for row in self.snapshots}
        day = local.date()
        additions = []
        for source, points in sorted(arms.items()):
            if not isinstance(source, str) or not source.strip() or len(source) > 100:
                raise ValueError("invalid comparison source")
            if (source, day) in known:
                continue
            original_issues = {model: utc_time(stamp).isoformat()
                               for model, stamp in weather_issues.get(source, {}).items()}
            if any(_stamp(value) > calculated_at for value in original_issues.values()):
                raise ValueError("comparison weather issue is in the future")
            rows = []
            previous = {}
            points = tuple(points)
            if any(not isinstance(point, ForecastPoint) for point in points):
                raise ValueError("comparison arms require ForecastPoint rows")
            for point in sorted(points, key=lambda p: (p.inverter_id, p.start)):
                if point.end <= received_at:
                    continue
                start = max(point.start, received_at)
                if (point.inverter_id not in self.output_caps
                        or max(point.power_w, point.baseline_w) > self.output_caps[point.inverter_id]
                        or point.inverter_id in previous and start < previous[point.inverter_id]):
                    raise ValueError("comparison point violates output scope")
                previous[point.inverter_id] = point.end
                rows.append((point.inverter_id, start.isoformat(), point.end.isoformat(),
                             point.start.isoformat(), point.power_w, point.baseline_w))
            additions.append({"source": source, "calculated_at": calculated_at.isoformat(),
                              "retrieved_at": received_at.isoformat(), "weather_issued_at": original_issues,
                              "status": ("unavailable" if not rows else "available"
                                         if {row[0] for row in rows} == set(self.output_caps) else "partial"),
                              "points": rows})
        # Validate and prepare the complete batch before mutating the archive.
        if (sum(len(row["points"]) for row in additions) > MAX_COMPARISON_POINTS
                or len(additions) > MAX_COMPARISON_SNAPSHOTS):
            raise ValueError("comparison capture batch exceeds retention bound")
        if additions:
            self.snapshots.extend(additions)
            self.revision += 1
        pruned = self.prune(received_at)
        return bool(additions) or pruned

    def prune(self, now):
        cutoff = utc_time(now) - timedelta(days=COMPARISON_RETENTION_DAYS)
        snapshots = [row for row in self.snapshots if _stamp(row["retrieved_at"]) >= cutoff]
        snapshots.sort(key=lambda row: (row["retrieved_at"], row["source"]))
        kept, points = [], 0
        for row in reversed(snapshots):
            count = len(row["points"])
            if len(kept) >= MAX_COMPARISON_SNAPSHOTS or points + count > MAX_COMPARISON_POINTS:
                break  # Never retain only a favorable subset of an old capture.
            kept.append(row)
            points += count
        selected = list(reversed(kept))
        changed = selected != self.snapshots
        if changed:
            self.snapshots = selected
            self.revision += 1
        return changed

    def to_dict(self, snapshots=None):
        """Export immutable capture rows; callers may freeze their outer tuple."""
        snapshots = self.snapshots if snapshots is None else snapshots
        return {"schema_version": 1, "config_fingerprint": self.fingerprint,
                "history_fingerprint": self.history_fingerprint, "output_caps_w": dict(self.output_caps),
                "timezone_name": self.zone.key, "point_columns": list(POINT_COLUMNS),
                "snapshots": [{**row, "weather_issued_at": dict(row["weather_issued_at"]),
                               "points": [list(point) for point in row["points"]]} for row in snapshots]}

    @classmethod
    def from_dict(cls, value, *, fingerprint=None, history_fingerprint=None, output_caps=None, timezone_name=None, as_of=None):
        as_of = utc_time(as_of or datetime.now(UTC))
        if (not isinstance(value, dict) or type(value.get("schema_version")) is not int
                or value["schema_version"] != 1 or not _fingerprint(value.get("config_fingerprint"))
                or not _fingerprint(value.get("history_fingerprint"), (64,))):
            raise ValueError("invalid comparison archive schema/binding")
        caps = value.get("output_caps_w")
        snapshots = value.get("snapshots")
        if (not isinstance(caps, dict) or not caps or any(not isinstance(key, str) or not key.strip()
                or isinstance(cap, bool) or not isinstance(cap, (float, int)) or not math.isfinite(cap) or cap <= 0
                for key, cap in caps.items()) or not isinstance(snapshots, list)
                or len(snapshots) > MAX_COMPARISON_SNAPSHOTS
                or value.get("point_columns") != list(POINT_COLUMNS)
                or not isinstance(value.get("timezone_name"), str)):
            raise ValueError("invalid comparison archive scope/size")
        for expected, actual in ((fingerprint, value["config_fingerprint"]),
                                 (history_fingerprint, value["history_fingerprint"]), (output_caps, caps),
                                 (timezone_name, value["timezone_name"])):
            if expected is not None and expected != actual:
                raise ValueError("incompatible comparison archive configuration")
        archive = cls(value["config_fingerprint"], value["history_fingerprint"], caps, value["timezone_name"])
        seen, total = set(), 0
        for snapshot in snapshots:
            if not isinstance(snapshot, dict):
                raise ValueError("invalid comparison capture")
            source = snapshot.get("source")
            if not isinstance(source, str) or not source.strip() or len(source) > 100:
                raise ValueError("invalid comparison source")
            calculated, receipt = _stamp(snapshot.get("calculated_at")), _stamp(snapshot.get("retrieved_at"))
            if receipt < calculated or receipt > as_of:
                raise ValueError("comparison capture predates calculation")
            if receipt.astimezone(archive.zone).hour < 18:
                raise ValueError("comparison receipt outside daily capture policy")
            key = source, receipt.astimezone(archive.zone).date()
            if key in seen:
                raise ValueError("duplicate daily comparison capture")
            seen.add(key)
            issues, rows = snapshot.get("weather_issued_at"), snapshot.get("points")
            if (not isinstance(issues, dict) or any(not isinstance(model, str) or _stamp(stamp) > calculated
                    for model, stamp in issues.items()) or not isinstance(rows, list)
                    or snapshot.get("status") not in {"available", "partial", "unavailable"}
                    or snapshot["status"] == "unavailable" and rows
                    or snapshot["status"] != "unavailable" and not rows):
                raise ValueError("invalid comparison weather provenance")
            total += len(rows)
            if total > MAX_COMPARISON_POINTS:
                raise ValueError("comparison archive exceeds point bound")
            previous = {}
            normalized = []
            for row in rows:
                if not isinstance(row, (list, tuple)) or len(row) != len(POINT_COLUMNS):
                    raise ValueError("invalid compact comparison point")
                inverter, start_text, end_text, original_text, power, baseline = row
                start, end, original = _stamp(start_text), _stamp(end_text), _stamp(original_text)
                if (inverter not in caps or start < receipt or original > start or end <= start
                        or inverter in previous and start < previous[inverter]):
                    raise ValueError("comparison point violates timing/scope")
                for value_w in (power, baseline):
                    if isinstance(value_w, bool) or not isinstance(value_w, (int, float)) or not math.isfinite(value_w) or not 0 <= value_w <= caps[inverter]:
                        raise ValueError("invalid comparison output power")
                previous[inverter] = end
                normalized.append((inverter, start.isoformat(), end.isoformat(), original.isoformat(), power, baseline))
            expected_status = ("unavailable" if not rows else "available" if set(previous) == set(caps) else "partial")
            if snapshot["status"] != expected_status:
                raise ValueError("comparison availability differs from stored stage support")
            archive.snapshots.append({"source": source, "calculated_at": calculated.isoformat(),
                "retrieved_at": receipt.isoformat(), "status": snapshot["status"],
                "weather_issued_at": {model: _stamp(stamp).isoformat() for model, stamp in issues.items()},
                "points": normalized})
        archive.restore_status = "restored"
        return archive

    def diagnostics(self):
        counts = Counter(row["source"] for row in self.snapshots)
        return {"schema_version": 1, "restore_status": self.restore_status,
                "retention_days_maximum": COMPARISON_RETENTION_DAYS, "maximum_points": MAX_COMPARISON_POINTS,
                "maximum_snapshots": MAX_COMPARISON_SNAPSHOTS, "capture_policy": "first_local_receipt_per_source_local_day_after_18",
                "snapshots": len(self.snapshots), "points": sum(len(row["points"]) for row in self.snapshots),
                "sources": dict(sorted(counts.items())),
                "first_receipt": min((row["retrieved_at"] for row in self.snapshots), default=None),
                "last_receipt": max((row["retrieved_at"] for row in self.snapshots), default=None),
                "scope": "prospective_comparison_only_no_training_or_accuracy_claim"}
