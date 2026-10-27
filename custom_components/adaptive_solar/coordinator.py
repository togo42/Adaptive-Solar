"""HA coordination, prospective feature archive and measured energy intervals."""
from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo
from bisect import bisect_left
from collections import Counter, defaultdict
import hashlib
import json
import logging
import math
from typing import Any, Mapping

from homeassistant.core import callback
from homeassistant.helpers.event import async_track_state_change_event, async_track_state_report_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    COUNTER_PLAUSIBILITY_WINDOW_SECONDS, DOMAIN, MAX_ARCHIVE_ROWS, MAX_ENERGY_GAP_SECONDS, MAX_TRAINING_ROWS,
    RETENTION_DAYS, SENSOR_MAX_AGE_SECONDS, UPDATE_SECONDS,
)
from .core.engine import ForecastEngine, shade_reference_powers
from .core.learning import (MAX_MEASUREMENT_EDGE_SECONDS, MIN_MEASUREMENT_COVERAGE,
                            MIN_TRAINING_SECONDS, ResidualLearner, feature_regime, ghi_feature_values, lead_bin)
from .core.models import ForecastPoint, Observation, SiteConfig, TrainingSample, midpoint_lead_hours, utc_time
from .core.rejection import RejectionDetails, detail_time
from .core.physics import PhysicsUnavailable, clear_sky_ghi, solar_position
from .core.shading import (
    BEAM_SHADE_STORE_KEY, BeamShadeTable, MAX_SHADE_CAP_FRACTION, MAX_SHADE_PAIR_SECONDS,
    MIN_SHADE_BEAM_ABS_W, MIN_SHADE_BEAM_CAP_FRACTION, MIN_SHADE_BEAM_SHARE,
    MIN_SHADE_CLEARNESS_INDEX, MIN_SHADE_CLEAR_SKY_W_M2, MIN_SHADE_ELEVATION_DEG,
    MIN_SHADE_SAMPLES, compute_beam_shade_factor, feature_solar_angles, shade_bin,
    shade_factors_compatible,
)
from .weather import WeatherError

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

    def note(self, inverter_id: str, outcome: str) -> None:
        """Transient event counts explain gating; they are never measured hours."""
        self.events[inverter_id][outcome] += 1
        self.last_outcome[inverter_id] = outcome

    def invalidate(self, inverter_id: str, reason: str = "curtailment_invalidated") -> None:
        self.pending.pop(inverter_id, None)
        self.dirty.add(inverter_id)
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
            self.note(inverter_id, "blocked_curtailment" if not safe else "invalid_or_unavailable_counter")
            return None
        if previous is None or dirty:
            self.anchors[inverter_id] = (time, energy_kwh)
            self.pending.pop(inverter_id, None)
            self.note(inverter_id, "anchor_after_invalidation" if dirty else "initial_anchor")
            return None
        start, before = previous
        duration = (time - start).total_seconds()
        delta = energy_kwh - before
        reset = energy_kwh < latest[1]
        if duration > MAX_ENERGY_GAP_SECONDS or (time - latest[0]).total_seconds() > MAX_ENERGY_GAP_SECONDS or reset:
            self.anchors[inverter_id] = (time, energy_kwh)
            self.pending.pop(inverter_id, None)
            self.note(inverter_id, "counter_reset" if reset else "measurement_gap")
            return None
        if inverter_id in self.pending and duration > COUNTER_PLAUSIBILITY_WINDOW_SECONDS:
            self.anchors[inverter_id] = (time, energy_kwh)
            self.pending.pop(inverter_id, None)
            self.note(inverter_id, "counter_aggregation_timeout")
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
            self.note(inverter_id, "power_above_output_cap")
            return None
        if inverter_id in self.pending:
            self.note(inverter_id, "accepted_deferred_delta")
        self.anchors[inverter_id] = (time, energy_kwh)
        self.pending.pop(inverter_id, None)
        self.note(inverter_id, "accepted_zero_delta" if delta == 0 else "accepted_positive_delta")
        return {"inverter_id": inverter_id, "start": start.isoformat(), "end": time.isoformat(), "observed_at": (observed_at or time).isoformat(), "energy_kwh": delta}


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


def _measurement_block(measured, index, a, b, as_of):
    """Longest unambiguous, finalized contiguous block wholly inside a target.

    Choice uses duration and then earliest start, never energy or model error.
    Future receipts are removed before duplicate/conflict checks. No energy is
    split at target boundaries and no gap between blocks is filled.
    """
    available = {}
    reasons = set()
    for part_index in range(index, len(measured)):
        part_start, part_end, part = measured[part_index]
        if part_start >= b:
            break
        if part_end > b:
            reasons.add("measurement_crosses_target_boundary")
            continue
        stamp = utc_time(datetime.fromisoformat(part["observed_at"]))
        if stamp < part_end:
            reasons.add("no_finalized_measurements")
            continue
        if as_of is not None and stamp > as_of:
            reasons.add("observation_not_yet_available")
            continue
        key = part_start, part_end
        previous = available.get(key)
        value = part["energy_kwh"]
        contract = part.get("curtailment_measurement_contract")
        if previous is not None:
            if previous[0] != value or previous[2] != contract:
                return None, {"overlapping_measurements"}
            stamp = min(stamp, previous[1])
        available[key] = value, stamp, contract
    if not available:
        return None, reasons or {"no_whole_measurement_inside_target"}
    blocks = []
    for (start, end), (energy, observed, _) in sorted(available.items()):
        if blocks and start < blocks[-1][1]:
            return None, {"overlapping_measurements"}
        if blocks and start == blocks[-1][1]:
            first, _, total, receipt = blocks[-1]
            blocks[-1] = first, end, total + energy, max(receipt, observed)
        else:
            if blocks:
                reasons.add("internal_measurement_gap")
            blocks.append((start, end, energy, observed))
    return max(blocks, key=lambda block: (block[1] - block[0], -block[0].timestamp())), reasons


def join_training(archive: list[dict], intervals: list[dict], *, diagnostics: dict | None = None,
                  as_of: datetime | None = None, shading: BeamShadeTable | None = None,
                  output_caps: Mapping[str, float] | None = None,
                  rejection_details: dict | None = None) -> list[TrainingSample]:
    """Join the longest eligible measured block to each forecast cell.

    Coverage >=92%, each edge missing <=180 seconds, and target cells >=30
    minutes are fixed before evaluation. Actual energy is summed only across
    exactly contiguous measured pieces. Early fragments cannot hide a longer
    valid later block; no boundary interpolation or internal gap filling.

    Optional diagnostics count unique original target cells, not forecast
    origins/regimes. Labels received after as_of are excluded before deduping;
    future targets are pending at as_of. Reasons may overlap
    (e.g. missing coverage AND an excessive edge); they are not sample counts.
    A valid cross-hour measurement may support a larger original target cell,
    but may never be clipped to fill an hourly boundary.

    A complete hour needs >=3312 measured seconds, with <=180 missing seconds
    at either edge. MAX_ENERGY_GAP_SECONDS limits a counter delta, not these
    separate alignment gates. Multiple origins reuse the same block selection.
    """
    by_inverter = {}
    for row in intervals:
        start, end = utc_time(datetime.fromisoformat(row["start"])), utc_time(datetime.fromisoformat(row["end"]))
        energy = row["energy_kwh"]
        if (end <= start or isinstance(energy, bool) or not isinstance(energy, (int, float))
                or not math.isfinite(energy) or energy < 0):
            continue
        by_inverter.setdefault(row["inverter_id"], []).append((start, end, row))
    for rows in by_inverter.values():
        rows.sort(key=lambda item: (item[0], item[1]))
    starts = {key: [item[0] for item in rows] for key, rows in by_inverter.items()}
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
                current_factor = shading.transmittance(inverter, angles[0], angles[1])
                stale_shade = not shade_factors_compatible(float(raw_shade_factor), current_factor)
            elif shading.filled_bins(inverter) > 0 or not shade_factors_compatible(float(raw_shade_factor), 1.0):
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
        measured = by_inverter.get(inverter, [])
        if target not in selected_blocks:
            selected_blocks[target] = _measurement_block(
                measured, bisect_left(starts.get(inverter, []), a), a, b, as_of)
        selected, reasons = selected_blocks[target]
        for reason in reasons:
            note(target, reason)
        if selected is None:
            continue
        start, stop, energy, observed = selected
        duration = (stop - start).total_seconds()
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
            accepted_spans[inverter].add((start, stop))
        key = (inverter, start, stop, issued)
        if key in seen:
            continue
        features = {**row["features"], "lead_hours": midpoint_lead_hours(issued, a, b), "target_duration_seconds": target_duration,
                    "measurement_coverage_fraction": coverage, "measurement_edge_fraction": edge_seconds / target_duration,
                    "measurement_edge_seconds": edge_seconds}
        if output_caps is not None and inverter in output_caps and "output_cap_w" not in features:
            features["output_cap_w"] = float(output_caps[inverter])
        samples.append(TrainingSample(issued_at=issued, start=start, end=stop, observed_at=observed,
            inverter_id=inverter, baseline_w=row["baseline_w"], actual_w=energy * 3600000 / duration,
            features=features, curtailed=False))
        seen.add(key)
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
        self._interval_latest: dict[tuple[str, datetime], tuple[int, dict]] = {}
        self._history_revision = 0
        self.learner_status: dict = {}
        self.input_quality: dict[str, str] = {}
        self._shade_inputs: dict[str, dict[str, Any]] = {}
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
        self._closing = False
        self._save_pending = False
        self._persistence_active = False
        self._store_writable = False
        # Old geometry/bindings must never train a newly configured system.
        fingerprint_data = config.to_dict()
        if fingerprint_data.get("irradiance_entity_id") is None:
            # Adding this optional field must not invalidate old history when
            # it remains unset; active new sensor bindings change the digest.
            fingerprint_data.pop("irradiance_entity_id", None)
        fingerprint = hashlib.sha256(json.dumps(fingerprint_data, sort_keys=True).encode()).hexdigest()[:16]
        self._fingerprint = fingerprint
        shade_data = dict(fingerprint_data)
        shade_data.pop("forecast_days", None)
        self._shade_fingerprint = hashlib.sha256(json.dumps(shade_data, sort_keys=True).encode()).hexdigest()
        # Observations/weather change forecast features, not measured output
        # lineage or already issued day-start forecasts. Physical/source and
        # civil-day provenance remain strict, including energy/curtailment IDs.
        history = config.to_dict()
        for key in ("weather_models", "forecast_days", "temperature_entity_id", "wind_entity_id", "irradiance_entity_id"):
            history.pop(key, None)
        for inverter in history["inverters"]:
            inverter.pop("power_entity_id", None)
        self._history_fingerprint = hashlib.sha256(json.dumps(history, sort_keys=True).encode()).hexdigest()
        self._store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.history_v2")
        self._legacy_store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")

    async def async_restore(self) -> None:
        """Restore data, not executable model objects or unverified anchors."""
        stored = await self._store.async_load()
        legacy = stored is None
        if legacy:
            stored = await self._legacy_store.async_load()
            self._store_writable = True  # New namespace; legacy is never written.
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
            return
        else:
            self._store_writable = True
            if stored["history_fingerprint"] != self._history_fingerprint:
                # A known physical/source change starts a fresh primary only
                # after successful setup; failed reloads preserve the old file.
                self.shading = BeamShadeTable()
                self.engine.shading = self.shading
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
                if not 0 < (end - start).total_seconds() <= 3600 or observed < end or isinstance(energy, bool) or not isinstance(energy, (float, int)) or not math.isfinite(energy) or energy < 0 or row["inverter_id"] not in caps or energy > caps[row["inverter_id"]] * (end - start).total_seconds() / 3600 * 1.1:
                    raise ValueError("invalid measured history")
            join_training(archive, intervals)
            snapshots = stored.get("daily_snapshots", {})
            if isinstance(snapshots, dict):
                for day, snapshot in snapshots.items():
                    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("energies"), dict):
                        raise ValueError("invalid snapshot structure")
                    cutoff = datetime.combine(datetime.fromisoformat(day).date(), time.min, ZoneInfo(self.site.timezone)).astimezone(UTC)
                    next_midnight = datetime.combine(datetime.fromisoformat(day).date() + timedelta(days=1), time.min, ZoneInfo(self.site.timezone)).astimezone(UTC)
                    hours = (next_midnight - cutoff).total_seconds() / 3600
                    if utc_time(datetime.fromisoformat(snapshot["issued_at"])) > cutoff or set(snapshot["energies"]) != set(caps) or any(isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0 or value > caps[key] * hours * 1.1 for key, value in snapshot["energies"].items()):
                        raise ValueError("invalid day-start snapshot")
            else:
                raise ValueError("invalid snapshots")
            shade_compatible = (
                stored.get("shade_fingerprint") == self._shade_fingerprint
                or ("shade_fingerprint" not in stored and stored.get("fingerprint") == self._fingerprint)
            )
            self.archive, self.intervals, self.daily_snapshots = archive, intervals, snapshots
            self.shading = (
                BeamShadeTable.from_dict(stored.get(BEAM_SHADE_STORE_KEY), inverter_ids=set(caps))
                if shade_compatible
                else BeamShadeTable()
            )
            self.engine.shading = self.shading
            self._prune(datetime.now(UTC))
        except (KeyError, TypeError, ValueError, OverflowError):
            self.archive, self.intervals, self.daily_snapshots, self._interval_latest = [], [], {}, {}
            self.shading = BeamShadeTable()
            self.engine.shading = self.shading
            self._store_writable = legacy  # Preserve corrupt existing primary.
            _LOGGER.warning("Ignoring invalid Adaptive Solar history")

    @callback
    def async_commit_setup(self) -> None:
        """Enable writes only after first refresh and platform setup succeeded."""
        if self._store_writable and not self._closing:
            self._persistence_active = True
            self._schedule_save()

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
        hour = start.replace(minute=0, second=0, microsecond=0)
        if end > hour + timedelta(hours=1):
            # A larger original forecast cell may contain the whole delta.
            # Do not discard measured energy merely because hours divide it.
            self.intervals.append(interval)
            if len(self.intervals) > MAX_TRAINING_ROWS:
                self._prune(datetime.now(UTC))
            self._history_revision += 1
            return
        key = (interval["inverter_id"], hour)
        position, previous = self._interval_latest.get(key, (len(self.intervals), None))
        if (previous is not None and previous["end"] == interval["start"]
                and previous.get("curtailment_measurement_contract") == interval.get("curtailment_measurement_contract")):
            merged = {**previous, "end": interval["end"], "observed_at": interval["observed_at"], "energy_kwh": previous["energy_kwh"] + interval["energy_kwh"]}
            self.intervals[position] = merged
            self._interval_latest[key] = (position, merged)
        else:
            self.intervals.append(interval)
            self._interval_latest[key] = (len(self.intervals) - 1, interval)
            if len(self.intervals) > MAX_TRAINING_ROWS:
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
                shading.record(inv.id, eval_sun.azimuth_deg, eval_sun.elevation_deg, power_time, factor)
        try:
            now_sun = eval_sun if eval_time == now else solar_position(config, now)
        except PhysicsUnavailable:
            now_sun = None
        az_now = now_sun.azimuth_deg if now_sun is not None else None
        el_now = now_sun.elevation_deg if now_sun is not None else None
        if shade_bin(az_now, el_now) is not None:
            if len(shading.bin_samples(inv.id, az_now, el_now)) < MIN_SHADE_SAMPLES:
                reasons.add("insufficient_samples")
        elif eval_sun is not None and shade_bin(eval_sun.azimuth_deg, eval_sun.elevation_deg) is not None:
            if len(shading.bin_samples(inv.id, eval_sun.azimuth_deg, eval_sun.elevation_deg)) < MIN_SHADE_SAMPLES:
                reasons.add("insufficient_samples")
        last_rejection = ";".join(sorted(reasons)) if reasons else None
        return shading.status_for(inv.id, az_now, el_now, last_rejection=last_rejection)

    async def _async_update_data(self):
        if self._closing:
            raise UpdateFailed("Coordinator is closed")
        now = datetime.now(UTC)
        self._prune(now)
        try:
            forecasts = await self.client.async_forecasts(now)
        except WeatherError as err:
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
            signature = (history_revision, now.astimezone(ZoneInfo(self.site.timezone)).date(), shade_key)
            alignment = {}
            targets = {}
            samples = join_training(
                archive, intervals, diagnostics=alignment, as_of=now,
                shading=shading, output_caps=output_caps, rejection_details=targets,
            )
            if self._learner is None or self._fit_signature != signature:
                self._learner = ResidualLearner(timezone_name=self.site.timezone, output_caps=output_caps)
                rows = {}
                self._learner.fit(samples, now, diagnostics=rows)
                self._fit_signature = signature
                self._training_snapshot = {"evaluated_at": detail_time(now), "alignment": alignment,
                                           "targets": targets, "rows": rows}
            # Diagnostic counts and details describe the SAME actual fit input.
            # A cache hit must not attach the current time to old row decisions.
            snapshot = self._training_snapshot
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
                status[inv.id] = {**self._learner.status.get(inv.id, {"state": "insufficient_history"}),
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
                                   "whole_measurements_only": True}}}
            return self.engine.forecast(
                forecasts, now, observations=observations, learner=self._learner, shading=shading
            ), status, shading

        result, status, shading = await self.hass.async_add_executor_job(calculate)
        if self._closing:
            raise UpdateFailed("Coordinator is closed")
        self.shading = shading
        self.engine.shading = shading
        self.learner_status = status
        if self.site.irradiance_entity_id:
            self.input_quality["irradiance_nowcast"] = result.model_status.get("irradiance", "ignored:no_observation")
        self._archive_result(result)
        self._schedule_save()
        return result

    def _archive_result(self, result) -> None:
        # Slot count is fixed by configured site size, never by outcome scores.
        # Budget includes future targets and has a 120-day / 60k-row upper bound;
        # it does not promise 120 days of actual paired history.
        slots = 3 if len(self.site.inverters) <= 3 else 2 if len(self.site.inverters) <= 6 else 1
        groups = {}
        candidates = list(self.archive)
        for point in result.points:
            if (result.issued_at > point.start or point.baseline_w <= 0
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
        self.archive = sorted(selected, key=lambda row: (row["start"], row["inverter_id"], row["issued_at"]))[-MAX_ARCHIVE_ROWS:]
        zone = ZoneInfo(self.site.timezone)
        for offset in range(self.site.forecast_days):
            day = result.issued_at.astimezone(zone).date() + timedelta(days=offset)
            start = datetime.combine(day, time.min, zone).astimezone(UTC)
            end = datetime.combine(day + timedelta(days=1), time.min, zone).astimezone(UTC)
            if result.issued_at > start:
                continue
            energies = {inv.id: result.energy_kwh(start, end, inv.id) for inv in self.site.inverters}
            if all(value is not None for value in energies.values()):
                self.daily_snapshots[day.isoformat()] = {"issued_at": result.issued_at.isoformat(), "energies": energies}

    def _prune(self, now: datetime) -> None:
        previous_size = len(self.archive), len(self.intervals)
        cutoff = (now - timedelta(days=RETENTION_DAYS)).isoformat()
        self.archive = [row for row in self.archive if row["end"] >= cutoff][-MAX_ARCHIVE_ROWS:]
        self.intervals = [row for row in self.intervals if row["end"] >= cutoff][-MAX_TRAINING_ROWS:]
        self._interval_latest = {(row["inverter_id"], datetime.fromisoformat(row["start"]).replace(minute=0, second=0, microsecond=0)): (index, row) for index, row in enumerate(self.intervals)}
        oldest_day = (now.astimezone(ZoneInfo(self.site.timezone)).date() - timedelta(days=7)).isoformat()
        self.daily_snapshots = {key: value for key, value in self.daily_snapshots.items() if key >= oldest_day}
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
        return {"fingerprint": self._fingerprint, "history_schema": 2, "history_fingerprint": self._history_fingerprint,
                "shade_fingerprint": self._shade_fingerprint,
                "learning_feature_contract": LEARNING_FEATURE_CONTRACT,
                BEAM_SHADE_STORE_KEY: self.shading.to_dict(),
                "archive": list(self.archive), "intervals": [dict(row) for row in self.intervals], "daily_snapshots": dict(self.daily_snapshots)}

    async def async_close(self) -> None:
        self._closing = True
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
        if self._unsub_reports is not None:
            self._unsub_reports()
            self._unsub_reports = None
        await self.async_shutdown()
        if self._persistence_active:
            self._persistence_active = False
            await self._store.async_save(self._stored())
