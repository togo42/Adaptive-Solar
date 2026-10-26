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
from typing import Any

from homeassistant.core import callback
from homeassistant.helpers.event import async_track_state_change_event, async_track_state_report_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN, MAX_ARCHIVE_ROWS, MAX_ENERGY_GAP_SECONDS, MAX_TRAINING_ROWS,
    RETENTION_DAYS, SENSOR_MAX_AGE_SECONDS, UPDATE_SECONDS,
)
from .core.engine import ForecastEngine
from .core.learning import (MAX_MEASUREMENT_EDGE_FRACTION, MIN_MEASUREMENT_COVERAGE,
                            MIN_TRAINING_SECONDS, ResidualLearner, feature_regime, ghi_feature_values, lead_bin)
from .core.models import ForecastPoint, Observation, SiteConfig, TrainingSample, midpoint_lead_hours, utc_time
from .weather import WeatherError

_LOGGER = logging.getLogger(__name__)

# Independent of site geometry and the HA Store's serialization version. Bump
# when archived baseline/feature semantics change; measurements are independent.
LEARNING_FEATURE_CONTRACT = "atomic-ghi-cohort-centered-weather-v2"


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
        self.dirty: set[str] = set()
        self.events: dict[str, Counter] = defaultdict(Counter)
        self.last_outcome: dict[str, str] = {}

    def note(self, inverter_id: str, outcome: str) -> None:
        """Transient event counts explain gating; they are never measured hours."""
        self.events[inverter_id][outcome] += 1
        self.last_outcome[inverter_id] = outcome

    def invalidate(self, inverter_id: str, reason: str = "curtailment_invalidated") -> None:
        self.dirty.add(inverter_id)
        self.note(inverter_id, reason)

    def record(self, inverter_id: str, time: datetime, energy_kwh: float | None, safe: bool, cap_w: float, *, observed_at: datetime | None = None) -> dict | None:
        previous = self.anchors.get(inverter_id)
        # Delayed or duplicate states cannot revise the measurement lineage or
        # consume a pending availability/curtailment invalidation.
        if previous is not None and time <= previous[0]:
            self.note(inverter_id, "nonforward_timestamp")
            return None
        dirty = inverter_id in self.dirty
        self.dirty.discard(inverter_id)
        if energy_kwh is None or not safe:
            self.anchors.pop(inverter_id, None)
            self.dirty.add(inverter_id)
            self.note(inverter_id, "blocked_curtailment" if not safe else "invalid_or_unavailable_counter")
            return None
        self.anchors[inverter_id] = (time, energy_kwh)
        if previous is None or dirty:
            self.note(inverter_id, "anchor_after_invalidation" if dirty else "initial_anchor")
            return None
        start, before = previous
        duration = (time - start).total_seconds()
        delta = energy_kwh - before
        if not 0 < duration <= MAX_ENERGY_GAP_SECONDS or delta < 0:
            self.note(inverter_id, "counter_reset" if delta < 0 else "measurement_gap")
            return None
        power = delta * 3600000 / duration
        # Small quantisation tolerance; gross unit mistakes/resets fail closed.
        if power > cap_w * 1.1:
            self.note(inverter_id, "power_above_output_cap")
            return None
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


def join_training(archive: list[dict], intervals: list[dict], *, diagnostics: dict | None = None,
                  as_of: datetime | None = None) -> list[TrainingSample]:
    """Join only nearly complete, centrally covered forecast cells.

    Coverage >=95%, each edge missing <=2.5%, and cells >=30 minutes are fixed
    before evaluation. Actual energy is summed only across exactly contiguous
    measured pieces, with no boundary interpolation or internal gap filling.
    Thus a 5-minute post-reset observation cannot label a whole forecast hour.

    Optional diagnostics count unique original target cells, not forecast
    origins/regimes. Labels received after as_of are excluded before deduping;
    future targets are pending at as_of. Reasons may overlap
    (e.g. missing coverage AND an excessive edge); they are not sample counts.
    A valid cross-hour measurement may support a larger original target cell,
    but may never be clipped to fill an hourly boundary.

    For a regular cadence d dividing an hour, nonzero phase p leaves p and
    d-p seconds at its edges. Both must be <=90s and their sum <=180s. Thus
    60/90s cadences qualify at any phase; aligned 5/15min cadences qualify,
    whereas shifted 5/15min cadences cannot qualify an original hourly cell.
    MAX_ENERGY_GAP_SECONDS limits a delta, not these separate alignment gates.
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
        rows.sort(key=lambda item: item[0])
    starts = {key: [item[0] for item in rows] for key, rows in by_inverter.items()}
    samples, seen = [], set()
    outcomes: dict[tuple, set[str]] = defaultdict(set)
    accepted_spans: dict[str, set[tuple]] = defaultdict(set)

    def note(target, reason):
        if diagnostics is not None:
            outcomes[target].add(reason)

    for row in archive:
        inverter = row["inverter_id"]
        a, b = utc_time(datetime.fromisoformat(row["start"])), utc_time(datetime.fromisoformat(row["end"]))
        issued = utc_time(datetime.fromisoformat(row["issued_at"]))
        target = inverter, a, b
        target_duration = (b - a).total_seconds()
        rejected = False
        for condition, reason in ((issued > a, "issued_after_target_start"),
                                  (target_duration < 1800, "target_shorter_than_minimum"),
                                  (row["features"].get("source_partial_at_issue", 0) != 0, "source_partial_at_issue")):
            if condition:
                note(target, reason)
                rejected = True
        if rejected:
            continue
        measured = by_inverter.get(inverter, [])
        index = bisect_left(starts.get(inverter, []), a)
        if index >= len(measured):
            note(target, "no_whole_measurement_inside_target")
            continue
        start = measured[index][0]
        if start >= b:
            note(target, "no_whole_measurement_inside_target")
            continue
        stop, energy, observed = start, 0.0, None
        for part_index in range(index, len(measured)):
            part_start, part_end, part = measured[part_index]
            if part_start != stop or part_end > b:
                note(target, "internal_measurement_gap" if part_start != stop
                     else "measurement_crosses_target_boundary")
                break
            stop = part_end
            energy += part["energy_kwh"]
            stamp = utc_time(datetime.fromisoformat(part["observed_at"]))
            observed = max(observed, stamp) if observed is not None else stamp
            if stop == b:
                break
        duration = (stop - start).total_seconds()
        coverage = duration / target_duration
        edge = max((start - a).total_seconds(), (b - stop).total_seconds()) / target_duration
        if (duration < MIN_TRAINING_SECONDS or coverage < MIN_MEASUREMENT_COVERAGE
                or edge > MAX_MEASUREMENT_EDGE_FRACTION or observed is None or observed < stop):
            if duration < MIN_TRAINING_SECONDS:
                note(target, "insufficient_measured_duration")
            if coverage < MIN_MEASUREMENT_COVERAGE:
                note(target, "insufficient_measurement_coverage")
            if edge > MAX_MEASUREMENT_EDGE_FRACTION:
                note(target, "measurement_edge_exceeded")
            if observed is None or observed < stop:
                note(target, "no_finalized_measurements")
            continue
        if as_of is not None and observed > as_of:
            note(target, "observation_not_yet_available")
            continue
        note(target, "accepted")
        if diagnostics is not None and (as_of is None or max(b, observed) <= as_of):
            accepted_spans[inverter].add((start, stop))
        key = (inverter, start, stop, issued)
        if key in seen:
            continue
        features = {**row["features"], "lead_hours": midpoint_lead_hours(issued, a, b), "target_duration_seconds": target_duration,
                    "measurement_coverage_fraction": coverage, "measurement_edge_fraction": edge}
        samples.append(TrainingSample(issued_at=issued, start=start, end=stop, observed_at=observed,
            inverter_id=inverter, baseline_w=row["baseline_w"], actual_w=energy * 3600000 / duration,
            features=features, curtailed=False))
        seen.add(key)
    if diagnostics is not None:
        diagnostics.clear()
        inverters = set(by_inverter) | {row["inverter_id"] for row in archive}
        for inverter in sorted(inverters):
            completed = [reasons for (key, _, end), reasons in outcomes.items()
                         if key == inverter and (as_of is None or end <= as_of)]
            rejected = [reasons for reasons in completed if "accepted" not in reasons]
            counts = Counter(reason for reasons in rejected for reason in reasons)
            measured_rows = by_inverter.get(inverter, [])
            seconds = _unique_seconds(accepted_spans[inverter])
            diagnostics[inverter] = {
                "count_scope": "unique_target_cells_not_forecast_origins",
                "completed_target_cells": len(completed),
                "pending_target_cells": sum(key == inverter and end > as_of for key, _, end in outcomes) if as_of is not None else 0,
                "accepted_target_cells": sum("accepted" in reasons for reasons in completed),
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
        self.engine = ForecastEngine(config)
        self.tracker = EnergyIntervalTracker()
        self.archive: list[dict] = []
        self.intervals: list[dict] = []
        self.daily_snapshots: dict[str, dict] = {}
        self._interval_latest: dict[tuple[str, datetime], tuple[int, dict]] = {}
        self._history_revision = 0
        self.learner_status: dict = {}
        self.input_quality: dict[str, str] = {}
        self._unsub = None
        self._unsub_reports = None
        self._measurement_valid_since: dict[str, datetime | None] = {}
        self._measurement_seen_changed: dict[str, datetime] = {}
        self._learner = None
        self._fit_signature = None
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
                return
        compatible_features = (stored.get("fingerprint") == self._fingerprint
                               and stored.get("learning_feature_contract") == LEARNING_FEATURE_CONTRACT)
        if not compatible_features:
            # Legacy features may include restored environmental/power reports
            # or have a different GHI-cohort/weather-time meaning.
            # Keep independently validated meters and actually published daily
            # snapshots, but never reuse those features or a derived learner.
            self._learner = self._fit_signature = None
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
            self.archive, self.intervals, self.daily_snapshots = archive, intervals, snapshots
            self._prune(datetime.now(UTC))
        except (KeyError, TypeError, ValueError, OverflowError):
            self.archive, self.intervals, self.daily_snapshots, self._interval_latest = [], [], {}, {}
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
        for inv in self.site.inverters:
            if inv.measurement_valid_entity_id:
                state = self.hass.states.get(inv.measurement_valid_entity_id)
                self._measurement_valid_since[inv.id] = started if self._measurement_flag_valid(state) else None
                if state is not None:
                    self._measurement_seen_changed[inv.id] = state.last_changed
        ids = [entity for inv in self.site.inverters for entity in (inv.energy_entity_id, inv.curtailed_entity_id, inv.measurement_valid_entity_id) if entity]
        if ids:
            self._unsub = async_track_state_change_event(self.hass, ids, self._async_state_changed)
        report_ids = [entity for inv in self.site.inverters for entity in (inv.energy_entity_id, inv.measurement_valid_entity_id) if entity]
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
            if entity == inv.curtailed_entity_id and not self._curtailment_safe(inv):
                self.tracker.invalidate(inv.id)
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

    def _curtailment_safe(self, inv) -> bool:
        if not inv.curtailed_entity_id:
            return True
        state = self.hass.states.get(inv.curtailed_entity_id)
        return state is not None and state.state == "off"

    def _record_energy(self, inv, state, now: datetime, *, reported_at: datetime | None = None) -> None:
        stamp = reported_at or (state.last_updated.astimezone(UTC) if state is not None else now)
        if inv.measurement_valid_entity_id:
            since = self._measurement_since(inv)
            if since is None or stamp <= since:
                self.tracker.anchors.pop(inv.id, None)
                self.tracker.invalidate(inv.id, "blocked_measurement_invalid" if since is None else "counter_predates_measurement_valid")
                return
        value = state_number(state, now, "energy", reported_at=stamp)
        interval = self.tracker.record(inv.id, stamp, value, self._curtailment_safe(inv), inv.output_cap_w, observed_at=now)
        if interval is not None:
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
            self._history_revision += 1
            return
        key = (interval["inverter_id"], hour)
        position, previous = self._interval_latest.get(key, (len(self.intervals), None))
        if previous is not None and previous["end"] == interval["start"]:
            merged = {**previous, "end": interval["end"], "observed_at": interval["observed_at"], "energy_kwh": previous["energy_kwh"] + interval["energy_kwh"]}
            self.intervals[position] = merged
            self._interval_latest[key] = (position, merged)
        else:
            self.intervals.append(interval)
            self._interval_latest[key] = (len(self.intervals) - 1, interval)
        self._history_revision += 1

    def _observations(self, now: datetime) -> tuple[Observation, ...]:
        observations = []
        self.input_quality = {}
        temp_state = self.hass.states.get(self.site.temperature_entity_id) if self.site.temperature_entity_id else None
        wind_state = self.hass.states.get(self.site.wind_entity_id) if self.site.wind_entity_id else None
        ghi_state = self.hass.states.get(self.site.irradiance_entity_id) if self.site.irradiance_entity_id else None
        ghi = state_number(ghi_state, now, "irradiance")
        if self.site.irradiance_entity_id:
            self.input_quality["irradiance"] = "valid" if ghi is not None else "ignored:missing_stale_future_or_invalid"
        temp = state_number(temp_state, now, "temperature")
        wind = state_number(wind_state, now, "wind")
        for key, entity, value in (("temperature", self.site.temperature_entity_id, temp), ("wind", self.site.wind_entity_id, wind)):
            if entity:
                self.input_quality[key] = "valid" if value is not None else "missing_stale_or_invalid"
        for inv in self.site.inverters:
            control = self.hass.states.get(inv.curtailed_entity_id) if inv.curtailed_entity_id else None
            control_state = "not_configured" if not inv.curtailed_entity_id else "clear" if control is not None and control.state == "off" else "active" if control is not None and control.state == "on" else "unknown"
            self.input_quality[f"curtailment_{inv.id}"] = control_state
            if inv.measurement_valid_entity_id:
                self.input_quality[f"measurement_valid_{inv.id}"] = self._measurement_validity(inv)
            if control_state in ("active", "unknown"):
                # This timestamps the control decision at issue, not a fabricated
                # power measurement. Its value is independently unavailable.
                observations.append(Observation(time=now, inverter_id=inv.id, curtailed=True))
            state = self.hass.states.get(inv.power_entity_id) if inv.power_entity_id else None
            power = state_number(state, now, "power")
            if power is not None and power > inv.output_cap_w * 1.1:
                power = None
            power_time = (getattr(state, "last_reported", None) or state.last_updated) if state is not None else None
            # Current off cannot rehabilitate a report from an earlier active
            # or unknown phase. last_changed marks this clear state's start;
            # require a genuinely newer HA power report, never a poll time.
            predates_clear = (power is not None and control_state == "clear"
                              and power_time <= control.last_changed)
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
                    ("ignored:predates_curtailment_clear" if predates_clear else
                     "valid" if power is not None else "missing_stale_or_invalid"))
            # Environmental readings carry their original timestamps separately:
            # refreshing a recent temperature must not freshen an old power value.
            if power is not None:
                observations.append(Observation(time=power_time, inverter_id=inv.id, power_w=power,
                                                curtailed=predates_clear or not self._curtailment_safe(inv)))
            for source, key, value in ((temp_state, "temperature_c", temp), (wind_state, "wind_m_s", wind), (ghi_state, "ghi_w_m2", ghi)):
                if value is not None:
                    observations.append(Observation(time=getattr(source, "last_reported", None) or source.last_updated, inverter_id=inv.id, **{key: value}))
        return tuple(observations)

    async def _async_update_data(self):
        if self._closing:
            raise UpdateFailed("Coordinator is closed")
        now = datetime.now(UTC)
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
                "anchor_present": inv.id in self.tracker.anchors,
                "pending_invalidation": inv.id in self.tracker.dirty,
                "last_event_outcome": self.tracker.last_outcome.get(inv.id),
                "event_counts_since_restart": dict(self.tracker.events.get(inv.id, {})),
                "event_count_scope": "received_events_not_measured_hours",
                "report_tracking": "value_changes_force_updates_and_filtered_state_reported",
                "unbound_curtailment_assumption": "unconstrained" if not inv.curtailed_entity_id else None,
                "report_evidence": "ha_receipt_not_physical_source_qualification",
            }

        signature = (self._history_revision, now.astimezone(ZoneInfo(self.site.timezone)).date())

        def calculate():
            alignment = {}
            samples = join_training(archive, intervals, diagnostics=alignment, as_of=now)
            if self._learner is None or self._fit_signature != signature:
                self._learner = ResidualLearner(timezone_name=self.site.timezone)
                self._learner.fit(samples, now)
                self._fit_signature = signature
            status = {}
            for inv in self.site.inverters:
                quality = alignment.get(inv.id, {"completed_target_cells": 0, "pending_target_cells": 0,
                                                "accepted_target_cells": 0, "rejected_target_cells": 0,
                                                "accepted_unique_measured_seconds": 0,
                                                "accepted_unique_target_hours": 0, "rejection_reasons": {}})
                reasons = list(quality["rejection_reasons"])
                if meter_quality[inv.id]["energy_source"] != "valid_reported_state":
                    reasons.append("missing_energy_source" if not inv.energy_entity_id else "invalid_or_unavailable_energy_source")
                if not quality["completed_target_cells"]:
                    reasons.append("no_completed_archived_forecast_targets")
                status[inv.id] = {**self._learner.status.get(inv.id, {"state": "insufficient_history"}),
                    "training_quality": {"meter": meter_quality[inv.id], "alignment": quality,
                        "blocking_reasons": sorted(set(reasons)),
                        "policy": {"min_coverage_fraction": MIN_MEASUREMENT_COVERAGE,
                                   "max_missing_edge_fraction": MAX_MEASUREMENT_EDGE_FRACTION,
                                   "minimum_source_target_seconds": 1800,
                                   "max_counter_delta_seconds": MAX_ENERGY_GAP_SECONDS,
                                   "whole_measurements_only": True}}}
            return self.engine.forecast(forecasts, now, observations=observations, learner=self._learner), status

        result, status = await self.hass.async_add_executor_job(calculate)
        if self._closing:
            raise UpdateFailed("Coordinator is closed")
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
        cutoff = (now - timedelta(days=RETENTION_DAYS)).isoformat()
        self.archive = [row for row in self.archive if row["end"] >= cutoff][-MAX_ARCHIVE_ROWS:]
        self.intervals = [row for row in self.intervals if row["end"] >= cutoff][-MAX_TRAINING_ROWS:]
        self._interval_latest = {(row["inverter_id"], datetime.fromisoformat(row["start"]).replace(minute=0, second=0, microsecond=0)): (index, row) for index, row in enumerate(self.intervals)}
        oldest_day = (now.astimezone(ZoneInfo(self.site.timezone)).date() - timedelta(days=7)).isoformat()
        self.daily_snapshots = {key: value for key, value in self.daily_snapshots.items() if key >= oldest_day}

    @callback
    def _schedule_save(self) -> None:
        # Do not postpone the write indefinitely when meters report each second.
        if self._persistence_active and not self._closing and not self._save_pending:
            self._save_pending = True
            self._store.async_delay_save(self._stored, 30)

    @callback
    def _stored(self) -> dict[str, Any]:
        self._save_pending = False
        return {"fingerprint": self._fingerprint, "history_schema": 2, "history_fingerprint": self._history_fingerprint,
                "learning_feature_contract": LEARNING_FEATURE_CONTRACT,
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
