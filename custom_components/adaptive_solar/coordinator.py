"""HA coordination, prospective feature archive and measured energy intervals."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo
from uuid import uuid4
from bisect import bisect_left
from collections import Counter, defaultdict
import json
import hashlib
import logging
import math
from time import perf_counter
from pathlib import Path
from typing import Any, Mapping

from homeassistant.core import callback
from homeassistant.helpers.event import async_track_state_change_event, async_track_state_report_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util.json import load_json

from .const import (
    COUNTER_PLAUSIBILITY_WINDOW_SECONDS, COUNTER_PENDING_WAIT_SECONDS, MEASUREMENT_CONTRACT, DOMAIN, MAX_ARCHIVE_ROWS, MAX_ENERGY_GAP_SECONDS, MAX_TRAINING_ROWS,
    MAX_MEASUREMENT_GAP_SECONDS_PER_HOUR, MAX_MEASUREMENT_SINGLE_GAP_SECONDS,
    RETENTION_DAYS, SENSOR_MAX_AGE_SECONDS, UPDATE_SECONDS, MAX_MEASUREMENT_PARTS, MAX_MEASUREMENT_PARTS_PER_ROW,
    MEASUREMENT_DETAIL_SECONDS,
)
from .core.engine import ForecastEngine, shade_reference_powers
from .core.comparison_archive import ComparisonArchive
from .core.early_bias import EarlyBiasShadow
from .core.learning import (MAX_MEASUREMENT_EDGE_SECONDS, MIN_MEASUREMENT_COVERAGE,
                            MIN_TRAINING_SECONDS, ResidualLearner, feature_regime, ghi_feature_values, lead_bin)
from .core.measurement import MeasurementIndex, MeasuredBlock, blocks as measured_blocks, can_follow, continuity, expand_interval, integrate_original
from .core.models import ForecastPoint, Observation, SiteConfig, TrainingSample, midpoint_lead_hours, utc_time
from .core.nowcast import PowerObservationHistory
from .core.rejection import RejectionDetails, detail_time
from .core.physics import PhysicsUnavailable, clear_sky_ghi, solar_position
from .core.shading import (
    BEAM_SHADE_STORE_KEY, BeamShadeTable, MAX_SHADE_CAP_FRACTION, MAX_SHADE_PAIR_SECONDS,
    MIN_SHADE_BEAM_ABS_W, MIN_SHADE_BEAM_CAP_FRACTION, MIN_SHADE_BEAM_SHARE,
    MIN_SHADE_CLEARNESS_INDEX, MIN_SHADE_CLEAR_SKY_W_M2, MIN_SHADE_ELEVATION_DEG,
    compute_beam_shade_factor, feature_solar_angles, shade_bin,
    shade_factors_compatible,
)
from .weather import WeatherError
from .snapshots import config_fingerprints, provenance, validate_snapshot

_LOGGER = logging.getLogger(__name__)

# Independent of site geometry and the HA Store's serialization version. Bump
# when archived baseline/feature semantics change; measurements are independent.
LEARNING_FEATURE_CONTRACT = "beam-shade-table-v1"
CURTAILMENT_MEASUREMENT_CONTRACT = "non-restored-control-v1"


def state_number(state, now: datetime, kind: str, *, max_age: int = SENSOR_MAX_AGE_SECONDS,
                 reported_at: datetime | None = None) -> float | None:
    """Read fresh finite HA values with explicit units; no assumed W/kWh."""
    if state is None or state.state in ("unknown", "unavailable"):
        return None
    if state.attributes.get("restored"):
        return None
    if isinstance(state.state, bool):
        return None
    if kind == "irradiance":
        max_age = min(max_age, 300)
    stamp = reported_at or getattr(state, "last_reported", None) or state.last_updated
    if stamp.tzinfo is None or not 0 <= (now - stamp).total_seconds() <= max_age:
        return None
    try:
        value = float(state.state)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    unit = state.attributes.get("unit_of_measurement")
    factors = {
        "power": {"W": 1, "kW": 1000, "MW": 1000000},
        "energy": {"Wh": 0.001, "kWh": 1, "MWh": 1000},
        "wind": {"m/s": 1, "km/h": 1 / 3.6, "mph": 0.44704, "kn": 0.514444444},
        "irradiance": {"W/m²": 1, "W/m2": 1, "kW/m²": 1000, "kW/m2": 1000},
    }
    if kind == "temperature":
        if unit == "°C":
            result = value
        elif unit == "°F":
            result = (value - 32) * 5 / 9
        elif unit == "K":
            result = value - 273.15
        else:
            return None
        return result if -100 <= result <= 70 else None
    if unit not in factors.get(kind, {}):
        return None
    result = value * factors[kind][unit]
    if not math.isfinite(result) or result < 0 or (kind == "wind" and result > 150) or (kind == "irradiance" and result > 1600):
        return None
    return result


class EnergyIntervalTracker:
    """Only uninterrupted non-curtailed meter differences form training labels.

    Anchors are deliberately never restored after a restart. There is no evidence
    of availability/curtailment during downtime. Whole cross-hour deltas remain
    stored, but only support targets containing them without an invented split.
    """

    def __init__(self) -> None:
        self.anchors: dict[str, tuple[datetime, float]] = {}
        self.pending: dict[str, tuple[datetime, float]] = {}
        self.dirty: set[str] = set()
        self.events: dict[str, Counter] = defaultdict(Counter)
        self.last_outcome: dict[str, str] = {}
        self.lineage: dict[str, str] = {}
        self.boundary_reason: dict[str, str] = {}

    def _break(self, inverter_id: str, reason: str) -> None:
        self.lineage[inverter_id] = uuid4().hex
        self.boundary_reason[inverter_id] = reason

    def note(self, inverter_id: str, outcome: str) -> None:
        """Transient event counts explain gating; they are never measured hours."""
        self.events[inverter_id][outcome] += 1
        self.last_outcome[inverter_id] = outcome

    def invalidate(self, inverter_id: str, reason: str = "curtailment_invalidated") -> None:
        self.pending.pop(inverter_id, None)
        self.dirty.add(inverter_id)
        self._break(inverter_id, reason)
        self.note(inverter_id, reason)

    def record(self, inverter_id: str, time: datetime, energy_kwh: float | None, safe: bool, cap_w: float, *, observed_at: datetime | None = None) -> dict | None:
        previous = self.anchors.get(inverter_id)
        latest = self.pending.get(inverter_id, previous)
        # Delayed or duplicate states cannot revise the measurement lineage or
        # consume a pending availability/curtailment invalidation.
        if latest is not None and time <= latest[0]:
            self.note(inverter_id, "nonforward_timestamp")
            return None
        dirty = inverter_id in self.dirty
        self.dirty.discard(inverter_id)
        if energy_kwh is None or not safe:
            self.anchors.pop(inverter_id, None)
            self.pending.pop(inverter_id, None)
            self.dirty.add(inverter_id)
            reason = "blocked_curtailment" if not safe else "invalid_or_unavailable_counter"
            self._break(inverter_id, reason)
            self.note(inverter_id, reason)
            return None
        if previous is None or dirty:
            self.anchors[inverter_id] = (time, energy_kwh)
            self.pending.pop(inverter_id, None)
            if inverter_id not in self.lineage:
                self._break(inverter_id, "restart_or_initial_anchor")
            self.note(inverter_id, "anchor_after_invalidation" if dirty else "initial_anchor")
            return None
        start, before = previous
        duration = (time - start).total_seconds()
        delta = energy_kwh - before
        reset = energy_kwh < latest[1]
        if duration > MAX_ENERGY_GAP_SECONDS or (time - latest[0]).total_seconds() > MAX_ENERGY_GAP_SECONDS or reset:
            reason = ("counter_reset" if reset else "counter_aggregation_timeout"
                      if inverter_id in self.pending and duration > COUNTER_PENDING_WAIT_SECONDS
                      else "measurement_gap")
            self.anchors[inverter_id] = (time, energy_kwh)
            self.pending.pop(inverter_id, None)
            self._break(inverter_id, reason)
            self.note(inverter_id, reason)
            return None
        power = delta * 3600000 / duration
        # Small quantisation tolerance; gross unit mistakes/resets fail closed.
        if power > cap_w * 1.1:
            # Rounding can publish a small energy step milliseconds after an
            # otherwise valid report. Keep the original endpoint temporarily,
            # without emitting energy, and validate the WHOLE delta against a
            # subsequent genuine report. Never clip energy or invent its time.
            # Both time and deferred energy are bounded; large jumps fail now.
            if (duration < COUNTER_PLAUSIBILITY_WINDOW_SECONDS
                    and delta <= cap_w * 1.1 * COUNTER_PLAUSIBILITY_WINDOW_SECONDS / 3600000):
                self.pending[inverter_id] = (time, energy_kwh)
                self.note(inverter_id, "deferred_power_check")
                return None
            self.anchors[inverter_id] = (time, energy_kwh)
            self.pending.pop(inverter_id, None)
            self._break(inverter_id, "power_above_output_cap")
            self.note(inverter_id, "power_above_output_cap")
            return None
        if inverter_id in self.pending:
            self.note(inverter_id, "accepted_deferred_delta")
        self.anchors[inverter_id] = (time, energy_kwh)
        self.pending.pop(inverter_id, None)
        self.note(inverter_id, "accepted_zero_delta" if delta == 0 else "accepted_positive_delta")
        return {"inverter_id": inverter_id, "start": start.isoformat(), "end": time.isoformat(), "observed_at": (observed_at or time).isoformat(), "energy_kwh": delta,
                "measurement_contract": MEASUREMENT_CONTRACT, "continuity_id": self.lineage[inverter_id],
                "boundary_reason": self.boundary_reason.pop(inverter_id, None)}


def lead_bucket(issued_at: datetime, start: datetime, end: datetime) -> int:
    """Exactly the same midpoint lead and boundaries used by the learner."""
    return lead_bin(midpoint_lead_hours(issued_at, start, end))


def _unique_seconds(spans) -> float:
    """Duration union, so neither origins nor overlapping cells multiply time."""
    merged = []
    for start, end in sorted(set(spans)):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return sum((end - start).total_seconds() for start, end in merged)


def _paired_forecast_origins(rows, *, slots, forecast_days):
    """Keep common temporal edge origins of adjacent original forecast cells.

    Selection uses only prospective issue/target times and the declared regime.
    Returning whole row pairs preserves an actually issued curve; independent
    per-cell representatives can otherwise delete every common short origin.
    """
    issues = defaultdict(dict)
    for row in rows:
        regime = feature_regime(row["features"])
        if (regime is None or row["features"].get("source_partial_at_issue", 0) != 0
                or row["baseline_w"] <= 0 or row["features"].get("sun_elevation_deg", 0) <= 0):
            continue
        start, end = utc_time(datetime.fromisoformat(row["start"])), utc_time(datetime.fromisoformat(row["end"]))
        issued = utc_time(datetime.fromisoformat(row["issued_at"]))
        if issued <= start:
            issues[row["inverter_id"], issued, regime][start, end] = row
    edges = {}
    centers = (3, 15, 36, 72, (96 + max(96, forecast_days * 24)) / 2)
    for (inverter, issued, regime), cells in issues.items():
        ordered = sorted(cells.items())
        for ((start, end), left), ((next_start, next_end), right) in zip(ordered, ordered[1:]):
            if end != next_start:
                continue
            bucket = lead_bucket(issued, start, end)
            key = inverter, start, end, next_end, regime, bucket
            previous = edges.get(key)
            candidate = issued, left, right
            center = 1.5 if regime == "ghi" and bucket == 0 else centers[bucket]
            def distance(value):
                return abs(midpoint_lead_hours(value[0], start, end) - center), -value[0].timestamp()
            if previous is None:
                edges[key] = candidate, candidate, candidate
            else:
                earliest, latest, middle = previous
                edges[key] = (candidate if issued < earliest[0] else earliest,
                              candidate if issued > latest[0] else latest,
                              candidate if distance(candidate) < distance(middle) else middle)
    selected = {}
    for earliest, latest, middle in edges.values():
        for _, left, right in ((middle,) if slots == 1 else (earliest, latest)):
            for row in (left, right):
                key = row["inverter_id"], row["start"], row["end"], row["issued_at"], feature_regime(row["features"])
                selected[key] = row
    return list(selected.values())


def _measurement_block(index, a, b):
    """Longest qualified block; gap seconds are never measured support."""
    candidates, reasons = measured_blocks(index, a, b)
    return (max(candidates, key=lambda block: (block.duration, -block.start.timestamp()))
            if candidates else None), reasons


def _endpoint_training(archive, measurement_indexes, existing, as_of, shading, output_caps):
    """Additional disjoint hourly windows bounded by genuine meter reports.

    Only v2 monitored lineages qualify. A frozen common issue must cover every
    measured piece; a cell mean may be integrated, a measured delta never split.
    Window selection uses timestamps alone, before looking at forecast errors.
    """
    occupied = defaultdict(list)
    for sample in existing:
        occupied[sample.inverter_id].append((sample.start, sample.end))
    occupied_starts = {}
    for inverter, spans in occupied.items():
        merged = []
        for start, end in sorted(set(spans)):
            if merged and start <= merged[-1][1]:
                merged[-1] = merged[-1][0], max(end, merged[-1][1])
            else:
                merged.append((start, end))
        occupied[inverter] = merged
        occupied_starts[inverter] = [start for start, _ in merged]
    sources = defaultdict(list)
    for row in archive:
        sources[row["inverter_id"]].append((utc_time(datetime.fromisoformat(row["start"])),
                                             utc_time(datetime.fromisoformat(row["end"])), row))
    for values in sources.values():
        values.sort(key=lambda item: item[0])
    result = []
    for inverter, index in measurement_indexes.items():
        current = None
        source_index, active_sources = 0, []
        source_rows = sources[inverter]
        for start, end, row in index.rows:
            # A bad interval excludes only its own indivisible support. Reset
            # the candidate at that boundary instead of disabling the entire
            # inverter's otherwise independent endpoint windows.
            if continuity(row) is None or index.conflicts.overlaps(start, end):
                current = None
                continue
            lineage = continuity(row)
            observed = utc_time(datetime.fromisoformat(row["observed_at"]))
            if current is None or row.get("boundary_reason") is not None or not can_follow(current, start, lineage):
                current = MeasuredBlock(start, end, row["energy_kwh"], observed, ((start, end),), lineage)
            else:
                gap = (start - current.end).total_seconds()
                current = MeasuredBlock(current.start, end, current.energy + row["energy_kwh"],
                                        max(current.observed, observed), (*current.support, (start, end)),
                                        lineage, current.gap_seconds + gap)
            elapsed = (current.end - current.start).total_seconds()
            if elapsed < 3600:
                continue
            candidate, current = current, None
            if elapsed > 4500 or candidate.duration < 3600 * MIN_MEASUREMENT_COVERAGE:
                continue
            position = bisect_left(occupied_starts.get(inverter, []), candidate.end) - 1
            if position >= 0 and occupied[inverter][position][1] > candidate.start:
                continue
            while source_index < len(source_rows) and source_rows[source_index][0] < candidate.end:
                active_sources.append(source_rows[source_index])
                source_index += 1
            active_sources = [part for part in active_sources if part[1] > candidate.start]
            forecasts = defaultdict(list)
            for _, _, source in active_sources:
                forecasts[source["issued_at"], feature_regime(source["features"])].append(source)
            accepted = []
            for (issued_text, regime), relevant in forecasts.items():
                issued = utc_time(datetime.fromisoformat(issued_text))
                if regime is None or issued > candidate.start:
                    continue
                valid = True
                for source in relevant:
                    feat = source["features"]
                    if (issued > utc_time(datetime.fromisoformat(source["start"]))
                            or feat.get("source_partial_at_issue", 0) != 0):
                        valid = False
                        break
                    factor = feat.get("beam_shade_factor", 1.0)
                    if isinstance(factor, bool) or not isinstance(factor, (int, float)) or not 0 <= factor <= 1:
                        valid = False
                        break
                    if shading is not None:
                        angles = feature_solar_angles(feat)
                        current_factor = shading.transmittance(inverter, *angles, as_of=as_of) if angles is not None else 1.0
                        if ((angles is None and shading.filled_bins(inverter, as_of=as_of) > 0)
                                or not shade_factors_compatible(factor, current_factor)):
                            valid = False
                            break
                integrated = integrate_original(relevant, candidate.support) if valid else None
                if integrated is None:
                    continue
                baseline, features = integrated
                # Regime is categorical. Averaging must never manufacture it.
                if feature_regime(features) != regime:
                    continue
                factors = [source["features"].get("beam_shade_factor", 1.0) for source in relevant]
                if factors and not all(shade_factors_compatible(factors[0], factor) for factor in factors):
                    continue
                features.update(lead_hours=midpoint_lead_hours(issued, candidate.start, candidate.end),
                                target_duration_seconds=elapsed,
                                measurement_coverage_fraction=candidate.duration / elapsed,
                                measurement_edge_fraction=0.0, measurement_edge_seconds=0.0,
                                measurement_gap_seconds=candidate.gap_seconds,
                                measurement_endpoint_window=1.0)
                if output_caps is not None and inverter in output_caps:
                    features.setdefault("output_cap_w", float(output_caps[inverter]))
                accepted.append(TrainingSample(issued, candidate.start, candidate.end, candidate.observed,
                                               inverter, baseline, candidate.energy * 3600000 / candidate.duration,
                                               features, measurement_support=candidate.support))
            if accepted:
                result.extend(accepted)
    return result


def join_training(archive: list[dict], intervals: list[dict], *, diagnostics: dict | None = None,
                  as_of: datetime | None = None, shading: BeamShadeTable | None = None,
                  output_caps: Mapping[str, float] | None = None,
                  rejection_details: dict | None = None) -> list[TrainingSample]:
    """Join the longest eligible measured block to each forecast cell.

    Coverage >=92%, each edge missing <=180 seconds, and target cells >=30
    minutes are fixed before evaluation. V2 monitored lineages allow bounded
    timestamp gaps, excluded from energy and measured duration. Opaque legacy
    pieces remain exact-only. Early fragments cannot hide a longer valid later
    block; no boundary interpolation or internal gap filling.

    Optional diagnostics count unique original target cells, not forecast
    origins/regimes. Labels received after as_of are excluded before deduping;
    future targets are pending at as_of. Reasons may overlap
    (e.g. missing coverage AND an excessive edge); they are not sample counts.
    A valid cross-hour measurement may support a larger original target cell,
    but may never be clipped to fill an hourly boundary.

    A complete hour needs >=3312 measured seconds, with <=180 missing seconds
    at either edge. MAX_ENERGY_GAP_SECONDS limits a counter delta, not these
    separate alignment gates. Multiple origins reuse the same block selection.
    Disjoint endpoint windows can additionally integrate a genuine common
    archived forecast issue over exactly their measured support.
    """
    by_inverter = {}
    for stored_row in intervals:
        for row in expand_interval(stored_row):
            start, end = utc_time(datetime.fromisoformat(row["start"])), utc_time(datetime.fromisoformat(row["end"]))
            energy = row["energy_kwh"]
            if (end <= start or isinstance(energy, bool) or not isinstance(energy, (int, float))
                    or not math.isfinite(energy) or energy < 0):
                continue
            by_inverter.setdefault(row["inverter_id"], []).append((start, end, row))
    for rows in by_inverter.values():
        rows.sort(key=lambda item: (item[0], item[1]))
    measurement_indexes = {key: MeasurementIndex(rows, as_of) for key, rows in by_inverter.items()}
    samples, seen = [], set()
    outcomes: dict[tuple, set[str]] = defaultdict(set)
    accepted_spans: dict[str, set[tuple]] = defaultdict(set)
    selected_blocks = {}

    def note(target, reason):
        if diagnostics is not None or rejection_details is not None:
            outcomes[target].add(reason)

    for row in archive:
        inverter = row["inverter_id"]
        a, b = utc_time(datetime.fromisoformat(row["start"])), utc_time(datetime.fromisoformat(row["end"]))
        issued = utc_time(datetime.fromisoformat(row["issued_at"]))
        target = inverter, a, b
        target_duration = (b - a).total_seconds()
        raw_shade_factor = row["features"].get("beam_shade_factor", 1.0)
        shade_factor_valid = (
            not isinstance(raw_shade_factor, bool)
            and isinstance(raw_shade_factor, (int, float))
            and math.isfinite(float(raw_shade_factor))
            and 0.0 <= float(raw_shade_factor) <= 1.0
        )
        stale_shade = not shade_factor_valid
        if shade_factor_valid and shading is not None:
            angles = feature_solar_angles(row["features"])
            if angles is not None:
                current_factor = shading.transmittance(inverter, angles[0], angles[1], as_of=as_of)
                stale_shade = not shade_factors_compatible(float(raw_shade_factor), current_factor)
            elif shading.filled_bins(inverter, as_of=as_of) > 0 or not shade_factors_compatible(float(raw_shade_factor), 1.0):
                stale_shade = True
        rejected = False
        for condition, reason in ((issued > a, "issued_after_target_start"),
                                  (target_duration < 1800, "target_shorter_than_minimum"),
                                  (row["features"].get("source_partial_at_issue", 0) != 0, "source_partial_at_issue"),
                                  (stale_shade, "stale_beam_shade_baseline")):
            if condition:
                note(target, reason)
                rejected = True
        if rejected:
            continue
        if as_of is not None and b > as_of:
            note(target, "target_not_yet_completed")
            continue
        if target not in selected_blocks:
            index = measurement_indexes.get(inverter)
            selected_blocks[target] = (_measurement_block(index, a, b) if index is not None
                                       else (None, {"no_whole_measurement_inside_target"}))
        selected, reasons = selected_blocks[target]
        for reason in reasons:
            note(target, reason)
        if selected is None:
            continue
        start, stop, energy, observed = selected.start, selected.end, selected.energy, selected.observed
        duration = selected.duration
        coverage = duration / target_duration
        edge_seconds = max((start - a).total_seconds(), (b - stop).total_seconds())
        if (duration < MIN_TRAINING_SECONDS or coverage < MIN_MEASUREMENT_COVERAGE
                or edge_seconds > MAX_MEASUREMENT_EDGE_SECONDS):
            if duration < MIN_TRAINING_SECONDS:
                note(target, "insufficient_measured_duration")
            if coverage < MIN_MEASUREMENT_COVERAGE:
                note(target, "insufficient_measurement_coverage")
            if edge_seconds > MAX_MEASUREMENT_EDGE_SECONDS:
                note(target, "measurement_edge_exceeded")
            continue
        note(target, "accepted")
        if diagnostics is not None and (as_of is None or max(b, observed) <= as_of):
            accepted_spans[inverter].update(selected.support)
        key = (inverter, start, stop, issued)
        if key in seen:
            continue
        features = {**row["features"], "lead_hours": midpoint_lead_hours(issued, a, b), "target_duration_seconds": target_duration,
                    "measurement_coverage_fraction": coverage, "measurement_edge_fraction": edge_seconds / target_duration,
                    "measurement_edge_seconds": edge_seconds,
                    "measurement_gap_seconds": selected.gap_seconds}
        if output_caps is not None and inverter in output_caps and "output_cap_w" not in features:
            features["output_cap_w"] = float(output_caps[inverter])
        samples.append(TrainingSample(issued_at=issued, start=start, end=stop, observed_at=observed,
            inverter_id=inverter, baseline_w=row["baseline_w"], actual_w=energy * 3600000 / duration,
            features=features, curtailed=False, measurement_support=selected.support))
        seen.add(key)
    # Shifted windows reuse original forecasts, never regenerate historical
    # physics. They may use only support not already selected by legacy cells.
    extra = _endpoint_training(archive, measurement_indexes, samples, as_of, shading, output_caps)
    samples.extend(extra)
    for sample in extra:
        target = sample.inverter_id, sample.start, sample.end
        note(target, "accepted")
        accepted_spans[sample.inverter_id].update(sample.measurement_support)
    if diagnostics is not None or rejection_details is not None:
        if diagnostics is not None:
            diagnostics.clear()
        if rejection_details is not None:
            rejection_details.clear()
        inverters = set(by_inverter) | {row["inverter_id"] for row in archive}
        for inverter in sorted(inverters):
            completed = [(start, end, reasons) for (key, start, end), reasons in outcomes.items()
                         if key == inverter and (as_of is None or end <= as_of)]
            rejected = [(start, end, reasons) for start, end, reasons in completed if "accepted" not in reasons]
            if rejection_details is not None:
                details = RejectionDetails()
                for start, end, reasons in rejected:
                    if start < end:
                        details.add(start, end, reasons)
                details.total = len(rejected)
                rejection_details[inverter] = details.to_dict()
            if diagnostics is None:
                continue
            counts = Counter(reason for _, _, reasons in rejected for reason in reasons)
            measured_rows = by_inverter.get(inverter, [])
            seconds = _unique_seconds(accepted_spans[inverter])
            diagnostics[inverter] = {
                "count_scope": "unique_target_cells_not_forecast_origins",
                "completed_target_cells": len(completed),
                "pending_target_cells": sum(key == inverter and end > as_of for key, _, end in outcomes) if as_of is not None else 0,
                "accepted_target_cells": sum("accepted" in reasons for _, _, reasons in completed),
                "rejected_target_cells": len(rejected), "rejection_reasons": dict(counts),
                "accepted_unique_measured_seconds": seconds, "accepted_unique_target_hours": int(seconds // 3600),
                "stored_measurement_intervals": len(measured_rows),
                "stored_unique_measured_seconds": _unique_seconds((start, end) for start, end, _ in measured_rows),
                "whole_cross_hour_intervals": sum(end > start.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
                                                  for start, end, _ in measured_rows),
            }
    return samples


class AdaptiveSolarCoordinator(DataUpdateCoordinator):
    """Refresh cheap local calculations every five minutes, weather hourly."""

    def __init__(self, hass, entry, config: SiteConfig, client) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=timedelta(seconds=UPDATE_SECONDS))
        self.site = config
        self.client = client
        self.shading = BeamShadeTable()
        self.engine = ForecastEngine(config, shading=self.shading)
        self.tracker = EnergyIntervalTracker()
        self.archive: list[dict] = []
        self.intervals: list[dict] = []
        self.daily_snapshots: dict[str, dict] = {}
        self.daily_snapshot_provenance: dict[str, dict] = {}
        self._pending_day_start_imports: dict[str, tuple[dict, dict]] = {}
        self._interval_latest: dict[tuple[str, datetime], tuple[int, dict]] = {}
        self._measurement_part_count = 0
        self._history_revision = 0
        self.learner_status: dict = {}
        self.input_quality: dict[str, str] = {}
        self._shade_inputs: dict[str, dict[str, Any]] = {}
        self._power_history = PowerObservationHistory(config.power_nowcast_window_minutes)
        self._unsub = None
        self._unsub_reports = None
        self._measurement_valid_since: dict[str, datetime | None] = {}
        self._measurement_seen_changed: dict[str, datetime] = {}
        self._curtailment_clear_since: dict[str, datetime | None] = {}
        self._curtailment_seen_changed: dict[str, datetime] = {}
        self._curtailment_seen_updated: dict[str, datetime] = {}
        self._curtailment_invalidated_at: dict[str, datetime] = {}
        self._curtailment_tracking_active = False
        self._learner = None
        self._fit_signature = None
        self._training_snapshot: dict | None = None
        self._bias_shadow = None
        self._bias_fit_signature = None
        self.bias_shadow_status: dict = {}
        self._shadow_archive_pending: tuple[ForecastPoint, ...] = ()
        self.resource_diagnostics = {"scope": "since_restart", "fit_count": 0, "fit_reuse_count": 0,
            "fit_failure_count": 0, "last_fit_success_at": None, "last_fit_failure_at": None,
            "fit_error": None, "join_seconds": 0.0, "fit_seconds": 0.0, "forecast_seconds": 0.0}
        self._closing = False
        self._save_pending = False
        self._persistence_active = False
        self._store_writable = False
        self._history_storage_status = "not_loaded"
        # Old geometry/bindings must never train a newly configured system.
        self._fingerprint, self._history_fingerprint, self._shade_fingerprint = config_fingerprints(config)
        self._comparison_archive = ComparisonArchive(self._fingerprint, self._history_fingerprint,
                                                    {inv.id: inv.output_cap_w for inv in config.inverters}, config.timezone)
        self._comparison_store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.comparison_v1",
                                       serialize_in_event_loop=False)
        self._comparison_store_writable = False
        self._comparison_persistence_active = False
        self._comparison_saved_revision = 0
        self._comparison_save_task = None
        self._comparison_storage_status = "not_loaded"
        self._store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.history_v2")
        self._legacy_store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")

    async def async_restore(self) -> None:
        """Restore data, not executable model objects or unverified anchors."""
        await self._async_restore_comparison()
        self._store_writable = False
        try:
            stored = await self.hass.async_add_executor_job(self._read_history_store, self._store)
        except Exception as err:
            self._history_storage_status = "invalid_primary_preserved_read_only"
            _LOGGER.warning("Preserving unreadable/unknown Adaptive Solar primary history: %s", type(err).__name__)
            return
        legacy = stored is None
        if legacy:
            self._store_writable = True  # New namespace; legacy is never written.
            self._history_storage_status = "new_primary"
            try:
                stored = await self.hass.async_add_executor_job(self._read_history_store, self._legacy_store)
            except Exception as err:
                # A missing Primary can start neutral. The unreadable legacy
                # source remains untouched and is never treated as evidence.
                self._history_storage_status = "invalid_legacy_preserved_new_primary"
                _LOGGER.warning("Preserving unreadable/unknown Adaptive Solar legacy history: %s", type(err).__name__)
                return
            if stored is None:
                return
            if not isinstance(stored, dict) or stored.get("fingerprint") != self._fingerprint:
                _LOGGER.warning("Retaining incompatible opaque legacy Adaptive Solar history without migration")
                return
        elif (not isinstance(stored, dict) or type(stored.get("history_schema")) is not int or stored["history_schema"] != 2
              or not isinstance(stored.get("history_fingerprint"), str)
              or len(stored["history_fingerprint"]) != 64
              or any(char not in "0123456789abcdef" for char in stored["history_fingerprint"])):
            _LOGGER.warning("Retaining unrecognized Adaptive Solar history without overwriting it")
            self._history_storage_status = "invalid_primary_preserved_read_only"
            return
        else:
            self._store_writable = True
            self._history_storage_status = "recognized_primary"
            if stored["history_fingerprint"] != self._history_fingerprint:
                # A known physical/source change starts a fresh primary only
                # after successful setup; failed reloads preserve the old file.
                self.shading = BeamShadeTable()
                self.engine.shading = self.shading
                # Already issued past/today forecasts are historical records,
                # not training data for the newly configured model. Only the
                # new self-describing provenance can cross this boundary.
                try:
                    self._restore_snapshots(stored, same_history=False)
                except (KeyError, TypeError, ValueError, OverflowError):
                    self.daily_snapshots, self.daily_snapshot_provenance = {}, {}
                    self._store_writable = False
                    self._history_storage_status = "invalid_primary_preserved_read_only"
                    _LOGGER.warning("Retaining invalid Adaptive Solar day-start provenance")
                return
        compatible_features = (stored.get("fingerprint") == self._fingerprint
                               and stored.get("learning_feature_contract") == LEARNING_FEATURE_CONTRACT)
        if not compatible_features:
            # Legacy features may include restored environmental/power reports
            # or have a different GHI-cohort/weather-time meaning.
            # Keep independently validated meters and actually published daily
            # snapshots, but never reuse those features or a derived learner.
            self._learner = self._fit_signature = None
            self._training_snapshot = None
            self.learner_status = {}
        try:
            archive = stored.get("archive", []) if compatible_features else []
            intervals = stored.get("intervals", [])
            if not isinstance(archive, list) or not isinstance(intervals, list):
                raise ValueError("invalid history arrays")
            # Reject malformed persistence as a whole rather than let bad rows
            # silently train. Dataclasses enforce timestamp/number validation.
            if len(archive) > MAX_ARCHIVE_ROWS or len(intervals) > MAX_TRAINING_ROWS:
                raise ValueError("history exceeds retention bound")
            part_count = 0
            for row in intervals:
                if not isinstance(row, dict):
                    raise ValueError("invalid measurement row")
                if "measurement_parts" in row:
                    parts = row["measurement_parts"]
                    if not isinstance(parts, (list, tuple)) or not 1 <= len(parts) <= MAX_MEASUREMENT_PARTS_PER_ROW:
                        raise ValueError("invalid original measurement parts")
                    part_count += len(parts)
                else:
                    part_count += 1
            if part_count > MAX_MEASUREMENT_PARTS:
                raise ValueError("measurement history exceeds original-parts bound")
            caps = {inv.id: inv.output_cap_w / 1000 for inv in self.site.inverters}
            for row in archive:
                start, end = utc_time(datetime.fromisoformat(row["start"])), utc_time(datetime.fromisoformat(row["end"]))
                if utc_time(datetime.fromisoformat(row["issued_at"])) > start:
                    raise ValueError("history was not prospective")
                ForecastPoint(start, end, row["inverter_id"], row["baseline_w"], row.get("power_w", row["baseline_w"]), features=row["features"])
                if (row["inverter_id"] not in caps
                        or max(row["baseline_w"], row.get("power_w", row["baseline_w"])) > caps[row["inverter_id"]] * 1000):
                    raise ValueError("forecast history violates output measurement boundary")
            for row in intervals:
                start, end = utc_time(datetime.fromisoformat(row["start"])), utc_time(datetime.fromisoformat(row["end"]))
                observed = utc_time(datetime.fromisoformat(row["observed_at"]))
                energy = row["energy_kwh"]
                if "measurement_contract" in row:
                    if (row["measurement_contract"] != MEASUREMENT_CONTRACT
                            or not isinstance(row.get("continuity_id"), str)
                            or len(row["continuity_id"]) != 32
                            or any(char not in "0123456789abcdef" for char in row["continuity_id"])
                            or (row.get("boundary_reason") is not None
                                and (not isinstance(row["boundary_reason"], str) or len(row["boundary_reason"]) > 80))):
                        raise ValueError("invalid measurement lineage")
                if not 0 < (end - start).total_seconds() <= 3600 or observed < end or isinstance(energy, bool) or not isinstance(energy, (float, int)) or not math.isfinite(energy) or energy < 0 or row["inverter_id"] not in caps or energy > caps[row["inverter_id"]] * (end - start).total_seconds() / 3600 * 1.1:
                    raise ValueError("invalid measured history")
                expand_interval(row, cap_w=caps[row["inverter_id"]] * 1000)
            join_training(archive, intervals)
            self._restore_snapshots(stored, same_history=True)
            shade_compatible = (
                stored.get("shade_fingerprint") == self._shade_fingerprint
                or ("shade_fingerprint" not in stored and stored.get("fingerprint") == self._fingerprint)
            )
            self.archive, self.intervals = archive, intervals
            self.shading = (
                BeamShadeTable.from_dict(stored.get(BEAM_SHADE_STORE_KEY), inverter_ids=set(caps))
                if shade_compatible
                else BeamShadeTable()
            )
            self.engine.shading = self.shading
            self._prune(datetime.now(UTC))
        except (KeyError, TypeError, ValueError, OverflowError):
            self.archive, self.intervals, self.daily_snapshots, self._interval_latest = [], [], {}, {}
            self.daily_snapshot_provenance = {}
            self.shading = BeamShadeTable()
            self.engine.shading = self.shading
            self._store_writable = legacy  # Preserve corrupt existing primary.
            self._history_storage_status = ("invalid_legacy_preserved_new_primary" if legacy
                                            else "invalid_primary_preserved_read_only")
            _LOGGER.warning("Ignoring invalid Adaptive Solar history")

    @staticmethod
    def _read_history_store(store):
        """Read each real file once without native load/migration side effects."""
        path = Path(store.path)
        try:
            path.lstat()
        except FileNotFoundError:
            return None  # Only an absent directory entry permits legacy fallback.
        envelope = load_json(str(path))
        minor = envelope.get("minor_version", 1) if isinstance(envelope, dict) else None
        if (not isinstance(envelope, dict) or type(envelope.get("version")) is not int
                or envelope["version"] != store.version or type(minor) is not int
                or minor != store.minor_version or envelope.get("key") != store.key
                or not isinstance(envelope.get("data"), dict)):
            raise ValueError("unrecognized history Store envelope")
        return envelope["data"]

    async def _async_restore_comparison(self) -> None:
        """Read optional large history in a worker, preserving invalid originals."""
        try:
            archive = await self.hass.async_add_executor_job(self._load_comparison)
        except Exception as err:
            self._comparison_storage_status = "invalid_store_preserved_read_only"
            self._comparison_archive.restore_status = "invalid_store_ignored"
            _LOGGER.warning("Preserving invalid optional comparison store: %s", type(err).__name__)
        else:
            self._comparison_store_writable = True
            self._comparison_storage_status = "writable"
            if archive is None:
                return
            if (archive.fingerprint != self._fingerprint or archive.history_fingerprint != self._history_fingerprint
                    or archive.output_caps != {inv.id: inv.output_cap_w for inv in self.site.inverters}
                    or archive.zone.key != self.site.timezone):
                self._comparison_archive.restore_status = "configuration_changed_new_archive"
                return
            self._comparison_archive = archive
            self._comparison_archive.prune(datetime.now(UTC))

    def _load_comparison(self):
        # A direct read is deliberate: Store.async_load renames broken JSON.
        # Preserve the original optional file unchanged, including unknown formats.
        path = Path(self._comparison_store.path)
        try:
            path.lstat()
        except FileNotFoundError:
            return None
        return ComparisonArchive.from_dict(self._read_comparison_data())

    def _read_comparison_data(self):
        envelope = load_json(self._comparison_store.path)
        if (not isinstance(envelope, dict) or type(envelope.get("version")) is not int
                or envelope["version"] != 1 or type(envelope.get("minor_version")) is not int
                or envelope["minor_version"] != 1 or envelope.get("key") != self._comparison_store.key):
            raise ValueError("unrecognized comparison Store envelope")
        return envelope.get("data")

    @staticmethod
    def _comparison_digest(value):
        # Streaming canonical hashing avoids a second full JSON string copy.
        checksum = hashlib.sha256()
        encoder = json.JSONEncoder(sort_keys=True, separators=(",", ":"), allow_nan=False)
        for chunk in encoder.iterencode(value):
            checksum.update(chunk.encode("utf-8"))
        return checksum.digest()

    def _comparison_payload(self, rows):
        payload = self._comparison_archive.to_dict(rows)
        return payload, self._comparison_digest(payload)

    def _comparison_saved(self, checksum):
        return self._comparison_digest(self._read_comparison_data()) == checksum

    @callback
    def _schedule_comparison_save(self) -> None:
        if (self._comparison_persistence_active and not self._closing
                and self._comparison_archive.revision != self._comparison_saved_revision
                and (self._comparison_save_task is None or self._comparison_save_task.done())):
            self._comparison_save_task = self.hass.async_create_task(
                self._async_save_comparison(), "Adaptive Solar comparison persistence")

    async def _async_save_comparison(self) -> None:
        if not self._comparison_persistence_active or not self._comparison_store_writable:
            return
        try:
            while self._comparison_archive.revision != self._comparison_saved_revision:
                revision = self._comparison_archive.revision
                # Captures never mutate their rows. Freeze the outer sequence
                # before letting a worker copy/export its potentially large body.
                rows = tuple(self._comparison_archive.snapshots)
                payload, checksum = await self.hass.async_add_executor_job(self._comparison_payload, rows)
                await self._comparison_store.async_save(payload)
                if not await self.hass.async_add_executor_job(self._comparison_saved, checksum):
                    raise ValueError("comparison storage readback mismatch")
                self._comparison_saved_revision = revision
                self._comparison_storage_status = "writable"
        except Exception as err:
            self._comparison_storage_status = "write_failed"
            _LOGGER.warning("Optional comparison persistence failed: %s", type(err).__name__)

    def _restore_snapshots(self, stored, *, same_history):
        snapshots, metadata = stored.get("daily_snapshots", {}), stored.get("daily_snapshot_provenance", {})
        if not isinstance(snapshots, dict) or not isinstance(metadata, dict) or len(snapshots) > 32:
            raise ValueError("invalid snapshots")
        now = datetime.now(UTC)
        today = now.astimezone(ZoneInfo(self.site.timezone)).date()
        current = provenance(self.site)
        restored, origins = {}, {}
        for day, snapshot in snapshots.items():
            origin = metadata.get(day)
            if origin is None:
                if not same_history:
                    continue  # Opaque old configurations cannot be guessed.
                # Matching physical provenance proves caps/identity, but a
                # weather/observation change may have changed the full hash.
                origin = {**current, "config_fingerprint": stored.get("fingerprint")}
            elif not isinstance(origin, dict):
                raise ValueError("invalid snapshot provenance")
            elif origin.get("site_identity") != current["site_identity"]:
                continue  # Different location/timezone/stage boundary.
            snapshot, origin = validate_snapshot(day, snapshot, origin, self.site)
            target = datetime.fromisoformat(day).date()
            if target < today - timedelta(days=7) or (not same_history and target > today):
                continue
            if target > today and origin["history_fingerprint"] != self._history_fingerprint:
                continue
            restored[day], origins[day] = snapshot, origin
        self.daily_snapshots, self.daily_snapshot_provenance = restored, origins

    async def async_restore_day_start(self, day, snapshot, source_site):
        """Explicit operator import of one missing historical issued forecast."""
        if not self._persistence_active or self._closing:
            raise ValueError("entry persistence is not writable")
        now = datetime.now(UTC)
        today = now.astimezone(ZoneInfo(self.site.timezone)).date()
        target = datetime.fromisoformat(day).date()
        if (not today - timedelta(days=7) <= target <= today
                or day in self.daily_snapshots or day in self._pending_day_start_imports):
            raise ValueError("only a missing retained historical day may be restored")
        snapshot, origin = validate_snapshot(day, snapshot, provenance(source_site, source="operator_restore"), self.site)
        # Keep proposals out of sensor-visible data while making concurrent
        # scheduled writes include them. Store.async_save logs some disk errors
        # without raising: verify the actual file rather than its memory cache.
        self._pending_day_start_imports[day] = snapshot, origin
        try:
            await self._store.async_save(self._stored())
            persisted = await self.hass.async_add_executor_job(load_json, self._store.path)
            data = persisted.get("data", {})
            if (data.get("daily_snapshots", {}).get(day) != snapshot
                    or data.get("daily_snapshot_provenance", {}).get(day) != origin):
                raise ValueError("day-start forecast storage readback failed")
            self.daily_snapshots[day], self.daily_snapshot_provenance[day] = snapshot, origin
        finally:
            self._pending_day_start_imports.pop(day, None)
        self.async_update_listeners()

    @callback
    def async_commit_setup(self) -> None:
        """Enable writes only after first refresh and platform setup succeeded."""
        if self._store_writable and not self._closing:
            self._persistence_active = True
            self._schedule_save()
        if self._comparison_store_writable and not self._closing:
            self._comparison_persistence_active = True
            self._schedule_comparison_save()

    @callback
    def async_start_tracking(self) -> None:
        """Track original meter/control/validity reports; never synthesize energy."""
        started = datetime.now(UTC)
        self._curtailment_tracking_active = True
        for inv in self.site.inverters:
            if inv.measurement_valid_entity_id:
                state = self.hass.states.get(inv.measurement_valid_entity_id)
                self._measurement_valid_since[inv.id] = started if self._measurement_flag_valid(state) else None
                if state is not None:
                    self._measurement_seen_changed[inv.id] = state.last_changed
            if inv.curtailed_entity_id:
                state = self.hass.states.get(inv.curtailed_entity_id)
                self._curtailment_clear_since[inv.id] = started if self._curtailment_flag_clear(state) else None
                if state is not None:
                    self._curtailment_seen_changed[inv.id] = state.last_changed
                    self._curtailment_seen_updated[inv.id] = state.last_updated
        ids = [entity for inv in self.site.inverters for entity in (inv.energy_entity_id, inv.curtailed_entity_id, inv.measurement_valid_entity_id) if entity]
        if ids:
            self._unsub = async_track_state_change_event(self.hass, ids, self._async_state_changed)
        report_ids = [entity for inv in self.site.inverters for entity in (inv.energy_entity_id, inv.curtailed_entity_id, inv.measurement_valid_entity_id) if entity]
        if report_ids:
            self._unsub_reports = async_track_state_report_event(self.hass, report_ids, self._async_state_reported)
        # Wait for the first actual numeric meter event before anchoring. A
        # pre-existing HA state may predate setup and its earlier interval has
        # no monitored availability/curtailment evidence.

    @callback
    def _async_state_changed(self, event) -> None:
        if self._closing:
            return
        entity = event.data["entity_id"]
        now = event.time_fired.astimezone(UTC)
        for inv in self.site.inverters:
            if entity == inv.measurement_valid_entity_id:
                self._measurement_flag_report(inv, event.data.get("new_state"), now)
            if entity == inv.curtailed_entity_id:
                self._curtailment_flag_report(inv, event.data.get("new_state"), now)
            if entity == inv.energy_entity_id:
                old, new = event.data.get("old_state"), event.data.get("new_state")
                # A forced report advances last_changed even for the same
                # value; an attribute-only update does not prove a measurement.
                if old is None or new is None or old.state != new.state or old.last_changed != new.last_changed:
                    self._record_energy(inv, new, now)
                else:
                    self.tracker.note(inv.id, "attribute_only_update_ignored")
                    if state_number(new, now, "energy", reported_at=new.last_updated) is None:
                        self.tracker.invalidate(inv.id, "counter_attributes_invalidated")
        self._schedule_save()

    @callback
    def _async_state_reported(self, event) -> None:
        if self._closing:
            return
        entity = event.data["entity_id"]
        now = event.time_fired.astimezone(UTC)
        # HA may mutate new_state.last_reported before this callback runs.
        # The timestamp captured in this event is the actual report boundary.
        stamp = event.data["last_reported"]
        for inv in self.site.inverters:
            if entity == inv.measurement_valid_entity_id:
                self._measurement_flag_report(inv, event.data.get("new_state"), max(now, stamp.astimezone(UTC)))
            if entity == inv.curtailed_entity_id:
                self._curtailment_flag_report(inv, event.data.get("new_state"), max(now, stamp.astimezone(UTC)))
            if entity == inv.energy_entity_id:
                self._record_energy(inv, event.data["new_state"], now, reported_at=stamp)
        self._schedule_save()

    @staticmethod
    def _measurement_flag_valid(state) -> bool:
        return state is not None and state.state == "on" and not state.attributes.get("restored")

    def _measurement_validity(self, inv) -> str:
        if not inv.measurement_valid_entity_id:
            return "not_configured"
        state = self.hass.states.get(inv.measurement_valid_entity_id)
        if self._measurement_flag_valid(state):
            return "valid"
        return "invalid" if state is not None and state.state in ("on", "off") else "unknown"

    def _measurement_flag_report(self, inv, state, received: datetime) -> None:
        # Use the event's state, not a newer state already in hass.states: an
        # off/on burst must retain the invalidation independently of ordering.
        if not self._measurement_flag_valid(state):
            self._measurement_valid_since[inv.id] = None
            self.tracker.anchors.pop(inv.id, None)
            self.tracker.invalidate(inv.id, "measurement_validity_invalidated")
        elif self._measurement_valid_since.get(inv.id) is None:
            self._measurement_valid_since[inv.id] = received
        if state is not None:
            self._measurement_seen_changed[inv.id] = state.last_changed
        self.input_quality[f"measurement_valid_{inv.id}"] = self._measurement_validity(inv)

    def _measurement_since(self, inv) -> datetime | None:
        """Original reports must follow monitoring startup and latest recovery.

        Flag on asserts that the external adapter has already resynchronized
        its original counter; it is neither an energy report nor curtailment.
        A cached state cannot establish an unmonitored measurement interval.
        """
        state = self.hass.states.get(inv.measurement_valid_entity_id)
        since = self._measurement_valid_since.get(inv.id)
        if (not self._measurement_flag_valid(state) or since is None
                or state.last_changed != self._measurement_seen_changed.get(inv.id)):
            return None  # a newer on transition is not processed/qualified yet
        return since

    @staticmethod
    def _curtailment_flag_clear(state) -> bool:
        return state is not None and state.state == "off" and not state.attributes.get("restored")

    def _curtailment_status(self, inv) -> str:
        if not inv.curtailed_entity_id:
            return "not_configured"
        state = self.hass.states.get(inv.curtailed_entity_id)
        if state is None or state.attributes.get("restored"):
            return "unknown"
        return {"off": "clear", "on": "active"}.get(state.state, "unknown")

    def _curtailment_safe(self, inv) -> bool:
        return self._curtailment_status(inv) in ("not_configured", "clear")

    def _curtailment_flag_report(self, inv, state, received: datetime) -> None:
        # Use the event's state, not a newer state already in hass.states: an
        # on/off or restored/off burst must retain invalidation independently of ordering.
        if not self._curtailment_flag_clear(state):
            self._curtailment_clear_since[inv.id] = None
            stamp = received
            if state is not None:
                stamp = max(received, state.last_changed.astimezone(UTC), state.last_updated.astimezone(UTC))
            prev_inv = self._curtailment_invalidated_at.get(inv.id)
            self._curtailment_invalidated_at[inv.id] = max(prev_inv, stamp) if prev_inv is not None else stamp
            self.tracker.anchors.pop(inv.id, None)
            self.tracker.invalidate(inv.id, "curtailment_invalidated")
        elif self._curtailment_clear_since.get(inv.id) is None:
            self._curtailment_clear_since[inv.id] = received
        if state is not None:
            self._curtailment_seen_changed[inv.id] = state.last_changed
            self._curtailment_seen_updated[inv.id] = state.last_updated
        self.input_quality[f"curtailment_{inv.id}"] = self._curtailment_status(inv)

    def _curtailment_since(self, inv) -> datetime | None:
        state = self.hass.states.get(inv.curtailed_entity_id)
        if not self._curtailment_flag_clear(state):
            return None
        if not self._curtailment_tracking_active:
            return datetime.min.replace(tzinfo=UTC)
        since = self._curtailment_clear_since.get(inv.id)
        if (since is None
                or state.last_changed != self._curtailment_seen_changed.get(inv.id)
                or state.last_updated != self._curtailment_seen_updated.get(inv.id)):
            return None
        return since

    def _record_energy(self, inv, state, now: datetime, *, reported_at: datetime | None = None) -> None:
        stamp = reported_at or (state.last_updated.astimezone(UTC) if state is not None else now)
        if inv.measurement_valid_entity_id:
            since = self._measurement_since(inv)
            if since is None or stamp <= since:
                self.tracker.anchors.pop(inv.id, None)
                self.tracker.invalidate(inv.id, "blocked_measurement_invalid" if since is None else "counter_predates_measurement_valid")
                return
        value = state_number(state, now, "energy", reported_at=stamp)
        if inv.curtailed_entity_id:
            clear_since = self._curtailment_since(inv)
            invalidated_at = self._curtailment_invalidated_at.get(inv.id)
            curtailment_safe = (
                clear_since is not None
                and stamp >= clear_since
                and (invalidated_at is None or stamp > invalidated_at)
            )
        else:
            curtailment_safe = True
        interval = self.tracker.record(inv.id, stamp, value, curtailment_safe, inv.output_cap_w, observed_at=now)
        if interval is not None:
            if inv.curtailed_entity_id:
                interval["curtailment_measurement_contract"] = CURTAILMENT_MEASUREMENT_CONTRACT
            self._append_interval(interval)

    def _append_interval(self, interval: dict) -> None:
        """Merge adjacent pieces within a UTC hour; retain whole crossings.

        Never split a meter delta across hour boundaries. That would need an
        unobserved within-interval production profile. A missing/blocked piece
        leaves a discontinuity and therefore starts a separate segment.
        """
        start, end = datetime.fromisoformat(interval["start"]), datetime.fromisoformat(interval["end"])
        incoming_parts = len(interval.get("measurement_parts", ())) or 1
        self._measurement_part_count += incoming_parts
        hour = start.replace(minute=0, second=0, microsecond=0)
        if end > hour + timedelta(hours=1):
            # A larger original forecast cell may contain the whole delta.
            # Do not discard measured energy merely because hours divide it.
            self.intervals.append(interval)
            if len(self.intervals) > MAX_TRAINING_ROWS or self._measurement_part_count > MAX_MEASUREMENT_PARTS:
                self._prune(datetime.now(UTC))
            self._history_revision += 1
            return
        key = (interval["inverter_id"], hour)
        position, previous = self._interval_latest.get(key, (len(self.intervals), None))
        if (previous is not None and previous["end"] == interval["start"]
                and previous.get("curtailment_measurement_contract") == interval.get("curtailment_measurement_contract")
                and continuity(previous) == continuity(interval)
                and interval.get("boundary_reason") is None
                and (len(previous.get("measurement_parts", ())) or 1) + incoming_parts <= MAX_MEASUREMENT_PARTS_PER_ROW):
            merged = {**previous, "end": interval["end"], "observed_at": interval["observed_at"], "energy_kwh": previous["energy_kwh"] + interval["energy_kwh"]}
            if continuity(interval) is not None:
                def parts(row):
                    return tuple(row.get("measurement_parts") or
                                 ((row["start"], row["end"], row["observed_at"], row["energy_kwh"]),))
                original = parts(previous)
                incoming = parts(interval)
                compacted = list(original)
                for part in incoming:
                    last = compacted[-1] if compacted else None
                    if (last is not None and last[1] == part[0]
                            and (datetime.fromisoformat(part[1]) - datetime.fromisoformat(last[0])).total_seconds()
                            <= MEASUREMENT_DETAIL_SECONDS):
                        compacted[-1] = (last[0], part[1],
                                         max(datetime.fromisoformat(last[2]), datetime.fromisoformat(part[2])).isoformat(),
                                         last[3] + part[3])
                    else:
                        compacted.append(part)
                merged["measurement_parts"] = tuple(compacted)
                self._measurement_part_count -= len(original) + len(incoming) - len(compacted)
                merged["observed_at"] = max(datetime.fromisoformat(previous["observed_at"]),
                                            datetime.fromisoformat(interval["observed_at"])).isoformat()
            self.intervals[position] = merged
            self._interval_latest[key] = (position, merged)
        else:
            self.intervals.append(interval)
            self._interval_latest[key] = (len(self.intervals) - 1, interval)
            if len(self.intervals) > MAX_TRAINING_ROWS:
                self._prune(datetime.now(UTC))
        if self._measurement_part_count > MAX_MEASUREMENT_PARTS:
            self._prune(datetime.now(UTC))
        self._history_revision += 1

    def _observations(self, now: datetime) -> tuple[Observation, ...]:
        observations = []
        self.input_quality = {}
        self._shade_inputs = {}
        temp_state = self.hass.states.get(self.site.temperature_entity_id) if self.site.temperature_entity_id else None
        wind_state = self.hass.states.get(self.site.wind_entity_id) if self.site.wind_entity_id else None
        ghi_state = self.hass.states.get(self.site.irradiance_entity_id) if self.site.irradiance_entity_id else None
        ghi = state_number(ghi_state, now, "irradiance")
        ghi_time = (
            utc_time(getattr(ghi_state, "last_reported", None) or ghi_state.last_updated)
            if ghi is not None and ghi_state is not None
            else None
        )
        if self.site.irradiance_entity_id:
            self.input_quality["irradiance"] = "valid" if ghi is not None else "ignored:missing_stale_future_or_invalid"
        temp = state_number(temp_state, now, "temperature")
        wind = state_number(wind_state, now, "wind")
        for key, entity, value in (("temperature", self.site.temperature_entity_id, temp), ("wind", self.site.wind_entity_id, wind)):
            if entity:
                self.input_quality[key] = "valid" if value is not None else "missing_stale_or_invalid"
        for inv in self.site.inverters:
            control = self.hass.states.get(inv.curtailed_entity_id) if inv.curtailed_entity_id else None
            control_state = self._curtailment_status(inv)
            self.input_quality[f"curtailment_{inv.id}"] = control_state
            if inv.measurement_valid_entity_id:
                self.input_quality[f"measurement_valid_{inv.id}"] = self._measurement_validity(inv)
            if control_state in ("active", "unknown"):
                # This timestamps the control decision at issue, not a fabricated
                # power measurement. Its value is independently unavailable.
                observations.append(Observation(time=now, inverter_id=inv.id, curtailed=True))
            state = self.hass.states.get(inv.power_entity_id) if inv.power_entity_id else None
            raw_power = state_number(state, now, "power")
            over_cap = raw_power is not None and raw_power > inv.output_cap_w * 1.1
            power = None if over_cap else raw_power
            power_time = (getattr(state, "last_reported", None) or state.last_updated) if state is not None else None
            raw_power_time = utc_time(power_time) if raw_power is not None and power_time is not None else None
            # Current off cannot rehabilitate a report from an earlier active
            # or unknown phase. Attribute-only removal of restored preserves
            # last_changed, so last_updated also bounds the clear phase.
            predates_clear = (raw_power is not None and control_state == "clear"
                              and power_time <= max(control.last_changed, control.last_updated))
            measurement_ignored = None
            if inv.measurement_valid_entity_id:
                since = self._measurement_since(inv)
                if since is None:
                    measurement_ignored = "ignored:measurement_invalid_or_not_monitored"
                elif power_time is not None and power_time <= since:
                    measurement_ignored = "ignored:predates_measurement_valid"
                if measurement_ignored:
                    power = None
            if inv.power_entity_id:
                self.input_quality[f"power_{inv.id}"] = (measurement_ignored or
                    ("ignored:predates_curtailment_clear" if (power is not None and predates_clear) else
                     "valid" if power is not None else "missing_stale_or_invalid"))
            self._shade_inputs[inv.id] = {
                "power_w": raw_power,
                "power_time": raw_power_time,
                "ghi_w_m2": ghi,
                "ghi_time": ghi_time,
                "curtailed_or_invalid": (
                    control_state in ("active", "unknown")
                    or predates_clear
                    or bool(measurement_ignored)
                    or over_cap
                ),
            }
            # Environmental readings carry their original timestamps separately:
            # refreshing a recent temperature must not freshen an old power value.
            if power is not None:
                observations.append(Observation(time=power_time, inverter_id=inv.id, power_w=power,
                                                curtailed=predates_clear or not self._curtailment_safe(inv)))
            for source, key, value in ((temp_state, "temperature_c", temp), (wind_state, "wind_m_s", wind), (ghi_state, "ghi_w_m2", ghi)):
                if value is not None:
                    observations.append(Observation(time=getattr(source, "last_reported", None) or source.last_updated, inverter_id=inv.id, **{key: value}))
        if self.site.power_nowcast_window_minutes:
            phases = {inv.id: (
                self._curtailment_status(inv), self._curtailment_invalidated_at.get(inv.id),
                self._curtailment_clear_since.get(inv.id), self._measurement_valid_since.get(inv.id),
            ) for inv in self.site.inverters}
            return self._power_history.update(observations, now, phases)
        return tuple(observations)

    @staticmethod
    def _evaluate_beam_shade_stage(config: SiteConfig, inv, forecasts, now: datetime,
                                   observations: tuple[Observation, ...],
                                   shading: BeamShadeTable,
                                   stage_input: dict[str, Any] | None = None) -> dict[str, Any]:
        if stage_input is not None:
            raw_power = stage_input.get("power_w")
            power_time = stage_input.get("power_time")
            ghi = stage_input.get("ghi_w_m2")
            ghi_time = stage_input.get("ghi_time")
            curtailed_or_invalid = bool(stage_input.get("curtailed_or_invalid"))
        else:
            own = [o for o in observations if o.inverter_id == inv.id]
            power_obs = next(
                (o for o in sorted(own, key=lambda item: item.time, reverse=True)
                 if o.power_w is not None and 0 <= (now - o.time).total_seconds() <= SENSOR_MAX_AGE_SECONDS),
                None,
            )
            ghi_obs = next(
                (o for o in sorted(own, key=lambda item: item.time, reverse=True)
                 if o.ghi_w_m2 is not None and 0 <= (now - o.time).total_seconds() <= 300),
                None,
            )
            raw_power = power_obs.power_w if power_obs is not None else None
            power_time = power_obs.time if power_obs is not None else None
            ghi = ghi_obs.ghi_w_m2 if ghi_obs is not None else None
            ghi_time = ghi_obs.time if ghi_obs is not None else None
            curtailed_or_invalid = any(
                o.curtailed or (o.power_w is not None and o.power_w > inv.output_cap_w * 1.1)
                for o in own
            )
        reasons: set[str] = set()
        if curtailed_or_invalid:
            reasons.add("curtailed_or_invalid")
        if (raw_power is None or power_time is None or ghi is None or ghi_time is None
                or abs((power_time - ghi_time).total_seconds()) > MAX_SHADE_PAIR_SECONDS):
            reasons.add("stale_or_unpaired")
        eval_time = power_time if power_time is not None else (ghi_time if ghi_time is not None else now)
        try:
            eval_sun = solar_position(config, eval_time)
            eval_clear_sky = clear_sky_ghi(config, eval_time)
        except PhysicsUnavailable:
            eval_sun = None
            eval_clear_sky = 0.0
        if (eval_sun is None or eval_sun.elevation_deg < MIN_SHADE_ELEVATION_DEG
                or eval_clear_sky < MIN_SHADE_CLEAR_SKY_W_M2):
            reasons.add("low_elevation")
        if ghi is not None and ghi_time is not None:
            try:
                ghi_clear_sky = eval_clear_sky if ghi_time == eval_time else clear_sky_ghi(config, ghi_time)
            except PhysicsUnavailable:
                ghi_clear_sky = 0.0
            if ghi_clear_sky <= 0.0 or (ghi / ghi_clear_sky) < MIN_SHADE_CLEARNESS_INDEX:
                reasons.add("low_clearness")
        ref_powers = shade_reference_powers(config, forecasts, now, inv.id, eval_time, observations)
        cap_limit = MAX_SHADE_CAP_FRACTION * inv.output_cap_w
        if raw_power is not None and raw_power <= inv.output_cap_w * 1.1 and raw_power >= cap_limit:
            reasons.add("at_cap")
        if ref_powers is None:
            reasons.add("no_reference")
        else:
            p0_w, p1_w = ref_powers
            beam_w = p1_w - p0_w
            min_beam_w = max(MIN_SHADE_BEAM_ABS_W, MIN_SHADE_BEAM_CAP_FRACTION * inv.output_cap_w)
            if beam_w < MIN_SHADE_BEAM_SHARE * p1_w or beam_w < min_beam_w:
                reasons.add("low_beam")
            if p1_w >= cap_limit:
                reasons.add("at_cap")
            if not reasons and eval_sun is not None and power_time is not None:
                factor = compute_beam_shade_factor(raw_power, p0_w, p1_w)
                shading.record(inv.id, eval_sun.azimuth_deg, eval_sun.elevation_deg, power_time, factor, as_of=now)
        try:
            now_sun = eval_sun if eval_time == now else solar_position(config, now)
        except PhysicsUnavailable:
            now_sun = None
        az_now = now_sun.azimuth_deg if now_sun is not None else None
        el_now = now_sun.elevation_deg if now_sun is not None else None
        if shade_bin(az_now, el_now) is not None:
            if not shading.status_for(inv.id, az_now, el_now, as_of=now)["released"]:
                reasons.add(shading.status_for(inv.id, az_now, el_now, as_of=now)["release_reason"])
        elif eval_sun is not None and shade_bin(eval_sun.azimuth_deg, eval_sun.elevation_deg) is not None:
            if not shading.status_for(inv.id, eval_sun.azimuth_deg, eval_sun.elevation_deg, as_of=now)["released"]:
                reasons.add(shading.status_for(inv.id, eval_sun.azimuth_deg, eval_sun.elevation_deg, as_of=now)["release_reason"])
        last_rejection = ";".join(sorted(reasons)) if reasons else None
        return shading.status_for(inv.id, az_now, el_now, as_of=now, last_rejection=last_rejection)

    async def _async_update_data(self):
        if self._closing:
            raise UpdateFailed("Coordinator is closed")
        now = datetime.now(UTC)
        self._prune(now)
        try:
            forecasts = await self.client.async_forecasts(now)
        except WeatherError as err:
            if not self._closing:
                self._capture_comparison(None, received_at=datetime.now(UTC))
            raise UpdateFailed(str(err)) from err
        if self._closing:
            raise UpdateFailed("Coordinator is closed")
        now = datetime.now(UTC)
        self._prune(now)
        observations = self._observations(now)
        # Copy event-loop-owned mutable rows before passing them to a worker.
        archive, intervals = list(self.archive), [dict(row) for row in self.intervals]
        shading = self.shading.copy()
        shade_inputs = {inv_id: dict(values) for inv_id, values in self._shade_inputs.items()}
        history_revision = self._history_revision
        meter_quality = {}
        for inv in self.site.inverters:
            state = self.hass.states.get(inv.energy_entity_id) if inv.energy_entity_id else None
            source = ("not_configured" if not inv.energy_entity_id else "valid_reported_state"
                      if state_number(state, now, "energy") is not None else "missing_stale_restored_or_invalid")
            validity = self._measurement_validity(inv)
            if inv.measurement_valid_entity_id:
                since = self._measurement_since(inv)
                if since is None:
                    source = "blocked_measurement_invalid_or_not_monitored"
                elif state is None or state.last_reported <= since:
                    source = "awaiting_report_after_measurement_valid"
            meter_quality[inv.id] = {
                "energy_source": source, "measurement_validity": validity,
                "measurement_validity_source_configured": bool(inv.measurement_valid_entity_id),
                "measurement_validity_scope": "current_external_input_not_curtailment_or_interval_proof",
                "curtailment_source_configured": bool(inv.curtailed_entity_id),
                "curtailment_safe_at_issue": self._curtailment_safe(inv),
                "legacy_curtailment_intervals": sum(1 for row in intervals if row["inverter_id"] == inv.id
                    and inv.curtailed_entity_id and row.get("curtailment_measurement_contract") != CURTAILMENT_MEASUREMENT_CONTRACT),
                "legacy_curtailment_scope": "retained_history_requires_operator_qualification",
                "anchor_present": inv.id in self.tracker.anchors,
                "pending_counter_aggregation": inv.id in self.tracker.pending,
                "pending_invalidation": inv.id in self.tracker.dirty,
                "last_event_outcome": self.tracker.last_outcome.get(inv.id),
                "event_counts_since_restart": dict(self.tracker.events.get(inv.id, {})),
                "event_count_scope": "received_events_not_measured_hours",
                "report_tracking": "value_changes_force_updates_and_filtered_state_reported",
                "unbound_curtailment_assumption": "unconstrained" if not inv.curtailed_entity_id else None,
                "report_evidence": "ha_receipt_not_physical_source_qualification",
            }

        output_caps = {inv.id: inv.output_cap_w for inv in self.site.inverters}

        def calculate():
            beam_shade_by_inv = {
                inv.id: self._evaluate_beam_shade_stage(
                    self.site, inv, forecasts, now, observations, shading, shade_inputs.get(inv.id)
                )
                for inv in self.site.inverters
            }
            shade_key = json.dumps(shading.to_dict(), sort_keys=True)
            alignment = {}
            targets = {}
            resources = dict(self.resource_diagnostics)
            started = perf_counter()
            samples = join_training(
                archive, intervals, diagnostics=alignment, as_of=now,
                shading=shading, output_caps=output_caps, rejection_details=targets,
            )
            resources["join_seconds"] = max(0.0, perf_counter() - started)
            resources["accepted_unique_measured_hours"] = {
                inv_id: values.get("accepted_unique_measured_seconds", 0) / 3600
                for inv_id, values in alignment.items()}
            # as_of can finalize a target/receipt even without a history mutation.
            # Compare actual joined inputs too; revision/day alone is insufficient.
            signature = (history_revision, now.astimezone(ZoneInfo(self.site.timezone)).date(), shade_key,
                         tuple(samples), json.dumps(alignment, sort_keys=True))
            learner, fit_signature, snapshot = self._learner, self._fit_signature, self._training_snapshot
            resources["fit_seconds"] = 0.0
            if self._learner is None or self._fit_signature != signature:
                rows = {}
                started = perf_counter()
                resources["fit_count"] += 1
                try:
                    candidate = ResidualLearner(timezone_name=self.site.timezone, output_caps=output_caps)
                    candidate.fit(samples, now, diagnostics=rows)
                except Exception as err:  # Optional learning must not suppress mandatory physics.
                    learner, fit_signature = None, None
                    rows = {}  # A partially fitted model has no valid row decisions.
                    resources.update({"fit_error": type(err).__name__, "last_fit_failure_at": now.isoformat(),
                                      "fit_failure_count": resources["fit_failure_count"] + 1})
                    _LOGGER.warning("Residual fitting failed; using physics: %s", type(err).__name__)
                else:
                    learner, fit_signature = candidate, signature
                    resources.update({"fit_error": None, "last_fit_success_at": now.isoformat()})
                resources["fit_seconds"] = max(0.0, perf_counter() - started)
                snapshot = {"evaluated_at": detail_time(now), "alignment": alignment,
                            "targets": targets, "rows": rows}
            else:
                resources["fit_reuse_count"] += 1
            # Diagnostic counts and details describe the SAME actual fit input.
            # A cache hit must not attach the current time to old row decisions.
            status = {}
            for inv in self.site.inverters:
                beam_shade = beam_shade_by_inv[inv.id]
                quality = snapshot["alignment"].get(inv.id, {"completed_target_cells": 0, "pending_target_cells": 0,
                                                "accepted_target_cells": 0, "rejected_target_cells": 0,
                                                "accepted_unique_measured_seconds": 0,
                                                "accepted_unique_target_hours": 0, "rejection_reasons": {}})
                reasons = list(quality["rejection_reasons"])
                if meter_quality[inv.id]["energy_source"] != "valid_reported_state":
                    reasons.append("missing_energy_source" if not inv.energy_entity_id else "invalid_or_unavailable_energy_source")
                if not quality["completed_target_cells"]:
                    reasons.append("no_completed_archived_forecast_targets")
                if resources["fit_error"]:
                    reasons.append("residual_fit_failed")
                status[inv.id] = {**(learner.status.get(inv.id, {"state": "insufficient_history"})
                                    if learner else {"state": "fit_failed"}),
                    "beam_shade": beam_shade,
                    "training_quality": {"meter": meter_quality[inv.id], "alignment": quality,
                        "rejection_details": {"schema_version": 1, "evaluated_at": snapshot["evaluated_at"],
                            "targets": snapshot["targets"].get(inv.id, RejectionDetails().to_dict()),
                            "rows": snapshot["rows"].get(inv.id, RejectionDetails().to_dict())},
                        "blocking_reasons": sorted(set(reasons)),
                        "policy": {"min_coverage_fraction": MIN_MEASUREMENT_COVERAGE,
                                   "max_missing_edge_seconds": MAX_MEASUREMENT_EDGE_SECONDS,
                                   "minimum_source_target_seconds": 1800,
                                   "max_counter_delta_seconds": MAX_ENERGY_GAP_SECONDS,
                                   "counter_plausibility_window_seconds": COUNTER_PLAUSIBILITY_WINDOW_SECONDS,
                                   "counter_pending_wait_seconds": COUNTER_PENDING_WAIT_SECONDS,
                                   "measurement_contract": MEASUREMENT_CONTRACT,
                                   "max_internal_gap_seconds": MAX_MEASUREMENT_SINGLE_GAP_SECONDS,
                                   "max_internal_gap_seconds_per_target_hour": MAX_MEASUREMENT_GAP_SECONDS_PER_HOUR,
                                   "endpoint_window_min_seconds": 3600,
                                   "endpoint_window_max_seconds": 4500,
                                   "gap_energy_and_duration_filled": False,
                                   "whole_measurements_only": True}}}
            started = perf_counter()
            result = self.engine.forecast(forecasts, now, observations=observations, learner=learner, shading=shading)
            resources["forecast_seconds"] = max(0.0, perf_counter() - started)
            # Shadow has no path into ForecastResult.points or operational learning.
            bias, bias_signature = self._bias_shadow, self._bias_fit_signature
            bias_key = tuple(samples)
            candidate_points = []
            bias_status = {}
            try:
                if bias is None or bias_signature != bias_key:
                    candidate_bias = EarlyBiasShadow(timezone_name=self.site.timezone, output_caps=output_caps)
                    candidate_bias.fit(samples, now)
                    bias, bias_signature = candidate_bias, bias_key
                bias_status = {"policy": "early-bias-shadow-v1", "operational_use": False,
                               "fit_error": None, "fit_evaluated_at": bias.evaluated_at, "learning": bias.status}
                for point in result.points:
                    prediction = bias.predict(point.inverter_id, point.features, point.baseline_w,
                                              output_caps[point.inverter_id])
                    if prediction.status == "shadow_bias_candidate":
                        candidate_points.append(replace(point, power_w=prediction.power_w, lower_w=None, upper_w=None))
            except Exception as err:  # An optional shadow cannot change published output.
                bias, bias_signature, candidate_points = None, None, []
                bias_status = {"policy": "early-bias-shadow-v1", "operational_use": False,
                               "fit_error": type(err).__name__, "learning": {}}
                _LOGGER.warning("Bias shadow failed: %s", type(err).__name__)
            return (result, status, shading, learner, fit_signature, snapshot, resources,
                    bias, bias_signature, bias_status, tuple(candidate_points))

        try:
            (result, status, shading, learner, fit_signature, snapshot, resources,
             bias, bias_signature, bias_status, candidate_points) = await self.hass.async_add_executor_job(calculate)
        except Exception:
            if not self._closing:
                self._capture_comparison(None, received_at=datetime.now(UTC))
            raise
        if self._closing:
            raise UpdateFailed("Coordinator is closed")
        self._learner, self._fit_signature, self._training_snapshot = learner, fit_signature, snapshot
        self.resource_diagnostics = resources
        self._bias_shadow, self._bias_fit_signature = bias, bias_signature
        self.bias_shadow_status = bias_status
        self._shadow_archive_pending = candidate_points
        self.shading = shading
        self.engine.shading = shading
        self.learner_status = status
        if self.site.irradiance_entity_id:
            self.input_quality["irradiance_nowcast"] = result.model_status.get("irradiance", "ignored:no_observation")
        # This is actual local availability after the complete executor result
        # returned, including optional shadow computation. issued_at alone is
        # the earlier calculation origin and cannot prove a day/target cutoff.
        self._archive_result(result, available_at=datetime.now(UTC))
        self._schedule_save()
        return result

    def _archive_result(self, result, *, available_at: datetime | None = None) -> None:
        available_at = utc_time(datetime.now(UTC) if available_at is None else available_at, "available_at")
        prospective_at = max(result.issued_at, available_at)
        self._archive_comparison(result)
        # Slot count is fixed by configured site size, never by outcome scores.
        # Budget includes future targets and has a 120-day / 60k-row upper bound;
        # it does not promise 120 days of actual paired history.
        slots = 3 if len(self.site.inverters) <= 3 else 2 if len(self.site.inverters) <= 6 else 1
        groups = {}
        candidates = list(self.archive)
        for point in result.points:
            if (prospective_at > point.start or point.baseline_w <= 0
                    or point.features.get("sun_elevation_deg", 0) <= 0
                    or point.features.get("source_partial_at_issue", 0) != 0
                    or feature_regime(point.features) is None):
                continue
            candidates.append({"issued_at": result.issued_at.isoformat(), "start": point.start.isoformat(),
                "end": point.end.isoformat(), "inverter_id": point.inverter_id,
                "baseline_w": point.baseline_w, "power_w": point.power_w,
                "features": {**point.features, **ghi_feature_values(point.features), "lead_hours": midpoint_lead_hours(result.issued_at, point.start, point.end)}})
        for row in candidates:
            if row["baseline_w"] <= 0 or row["features"].get("sun_elevation_deg", 0) <= 0 or row["features"].get("source_partial_at_issue", 0) != 0 or feature_regime(row["features"]) is None:
                continue
            lead = midpoint_lead_hours(datetime.fromisoformat(row["issued_at"]), datetime.fromisoformat(row["start"]), datetime.fromisoformat(row["end"]))
            key = (row["inverter_id"], row["start"], row["end"], lead_bin(lead), feature_regime(row["features"]))
            # Repeated identical origins never take multiple representative slots.
            groups.setdefault(key, {})[row["issued_at"]] = row
        selected = []
        centers = (3, 15, 36, 72, (96 + max(96, self.site.forecast_days * 24)) / 2)
        for key, values in groups.items():
            rows = list(values.values())
            def lead(row):
                return midpoint_lead_hours(datetime.fromisoformat(row["issued_at"]), datetime.fromisoformat(row["start"]), datetime.fromisoformat(row["end"]))
            regime, index = key[-1], key[-2]
            center = 1.5 if regime == "ghi" and index == 0 else centers[index]
            middle = min(rows, key=lambda row: (abs(lead(row) - center), -datetime.fromisoformat(row["issued_at"]).timestamp()))
            # NWP representatives are never displaced by GHI or sensor failure.
            # Keep at most two additional GHI edge origins per bin (one for
            # >=7 inverters); total row/date limits remain hard upper bounds.
            budget = (2 if len(self.site.inverters) <= 6 else 1) if regime == "ghi" else slots
            choices = [middle] if budget == 1 else [min(rows, key=lead), max(rows, key=lead)]
            if budget == 3:
                choices.append(middle)
            selected.extend({row["issued_at"]: row for row in choices}.values())
        paired = _paired_forecast_origins(candidates, slots=1 if len(self.site.inverters) >= 7 else 2,
                                          forecast_days=self.site.forecast_days)
        def target_bin(row):
            return (row["inverter_id"], row["start"], row["end"], feature_regime(row["features"]),
                    lead_bucket(datetime.fromisoformat(row["issued_at"]), datetime.fromisoformat(row["start"]),
                                datetime.fromisoformat(row["end"])))
        paired_targets = {target_bin(row)
                          for row in paired}
        # Replace independently chosen origins for paired targets, rather
        # than silently doubling their full old row budget. Isolated cells
        # keep the established per-cell representatives unchanged.
        selected = [row for row in selected if target_bin(row) not in paired_targets]
        selected.extend(paired)
        self.archive = sorted(selected, key=lambda row: (row["start"], row["inverter_id"], row["issued_at"]))[-MAX_ARCHIVE_ROWS:]
        zone = ZoneInfo(self.site.timezone)
        for offset in range(self.site.forecast_days):
            day = result.issued_at.astimezone(zone).date() + timedelta(days=offset)
            start = datetime.combine(day, time.min, zone).astimezone(UTC)
            end = datetime.combine(day + timedelta(days=1), time.min, zone).astimezone(UTC)
            if prospective_at > start:
                continue
            energies = {inv.id: result.energy_kwh(start, end, inv.id) for inv in self.site.inverters}
            if all(value is not None for value in energies.values()):
                self.daily_snapshots[day.isoformat()] = {"issued_at": result.issued_at.isoformat(), "energies": energies}
                self.daily_snapshot_provenance[day.isoformat()] = provenance(self.site)

    def _archive_comparison(self, result) -> None:
        """Archive prospective comparison arms without adding training rows."""
        self._capture_comparison(result, received_at=datetime.now(UTC))

    def _capture_comparison(self, result, *, received_at) -> None:
        """Record a real attempt, including a failed calculation's empty arms."""
        if self._closing:
            return
        arms = {"adaptive": result.points if result is not None else (),
                "operative_baseline": tuple(ForecastPoint(point.start, point.end, point.inverter_id,
                        point.baseline_w, point.baseline_w) for point in result.points) if result is not None else (),
                "shadow:early_bias": self._shadow_archive_pending if result is not None else ()}
        issues = {source: dict(result.member_issued_at) if result is not None else {} for source in arms}
        models = set(self.site.weather_models) | (set(result.member_points) if result is not None else set())
        for model in models:
            source = f"nwp:{model}"
            arms[source] = result.member_points.get(model, ()) if result is not None else ()
            issues[source] = ({model: result.member_issued_at[model]}
                              if result is not None and model in result.member_issued_at else {})
        for snapshot in self._comparison_archive.snapshots:
            arms.setdefault(snapshot["source"], ())
            issues.setdefault(snapshot["source"], {})
        try:
            self._comparison_archive.capture(arms,
                calculated_at=result.issued_at if result is not None else received_at,
                received_at=received_at, weather_issues=issues)
        except (KeyError, TypeError, ValueError, OverflowError):
            self._comparison_archive.restore_status = "capture_rejected"
            _LOGGER.warning("Rejected optional comparison capture; forecast and training history remain independent")
        else:
            # The dirty revision also retries a previously failed native write,
            # retaining the original receipt rather than constructing a new one.
            self._schedule_comparison_save()

    def _prune(self, now: datetime) -> None:
        if self._comparison_archive.prune(now):
            self._schedule_comparison_save()
        previous_size = len(self.archive), len(self.intervals)
        cutoff = (now - timedelta(days=RETENTION_DAYS)).isoformat()
        self.archive = [row for row in self.archive if row["end"] >= cutoff][-MAX_ARCHIVE_ROWS:]
        self.intervals = [row for row in self.intervals if row["end"] >= cutoff][-MAX_TRAINING_ROWS:]
        kept, count = [], 0
        for row in reversed(self.intervals):
            size = len(row.get("measurement_parts", ())) or 1
            if count + size > MAX_MEASUREMENT_PARTS:
                break
            kept.append(row)
            count += size
        self.intervals = list(reversed(kept))
        self._measurement_part_count = count
        self._interval_latest = {(row["inverter_id"], datetime.fromisoformat(row["start"]).replace(minute=0, second=0, microsecond=0)): (index, row) for index, row in enumerate(self.intervals)}
        oldest_day = (now.astimezone(ZoneInfo(self.site.timezone)).date() - timedelta(days=7)).isoformat()
        self.daily_snapshots = {key: value for key, value in self.daily_snapshots.items() if key >= oldest_day}
        self.daily_snapshot_provenance = {key: value for key, value in self.daily_snapshot_provenance.items()
                                          if key in self.daily_snapshots}
        if previous_size != (len(self.archive), len(self.intervals)):
            self._history_revision += 1

    @callback
    def _schedule_save(self) -> None:
        # Do not postpone the write indefinitely when meters report each second.
        if self._persistence_active and not self._closing and not self._save_pending:
            self._save_pending = True
            self._store.async_delay_save(self._stored, 30)

    @callback
    def _stored(self) -> dict[str, Any]:
        self._save_pending = False
        # Enforce the same bounds the reader requires even if no forecast
        # refresh succeeds between meter reports, delayed writes or shutdown.
        self._prune(datetime.now(UTC))
        snapshots = dict(self.daily_snapshots)
        origins = {day: self.daily_snapshot_provenance.get(day, provenance(self.site)) for day in snapshots}
        for day, (snapshot, origin) in self._pending_day_start_imports.items():
            snapshots[day], origins[day] = snapshot, origin
        return {"fingerprint": self._fingerprint, "history_schema": 2, "history_fingerprint": self._history_fingerprint,
                "shade_fingerprint": self._shade_fingerprint,
                "learning_feature_contract": LEARNING_FEATURE_CONTRACT,
                "measurement_contract": MEASUREMENT_CONTRACT,
                BEAM_SHADE_STORE_KEY: self.shading.to_dict(),
                "archive": list(self.archive), "intervals": [dict(row) for row in self.intervals],
                "daily_snapshots": snapshots, "daily_snapshot_provenance": origins}

    async def async_close(self) -> None:
        self._closing = True
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
        if self._unsub_reports is not None:
            self._unsub_reports()
            self._unsub_reports = None
        await self.async_shutdown()
        if self._comparison_save_task is not None:
            await self._comparison_save_task
        if self._persistence_active:
            self._persistence_active = False
            await self._store.async_save(self._stored())
        if self._comparison_persistence_active:
            self._comparison_archive.prune(datetime.now(UTC))
            await self._async_save_comparison()
            self._comparison_persistence_active = False
