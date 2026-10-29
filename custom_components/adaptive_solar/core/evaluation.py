"""Archive comparison on an explicitly declared, common evaluation schedule.

CLI-friendly entry point::

    report = evaluate_forecasts(
        [ForecastRecord.from_dict(x) for x in payload['forecasts']],
        [ActualRecord.from_dict(x) for x in payload['actuals']],
        [EvaluationWindow.from_dict(x) for x in payload['windows']],
        as_of=datetime.fromisoformat(payload['as_of']),
    )

Record timestamps are ISO-8601 strings and powers interval means in W. Each
window declares a common issue cutoff and an expected inverter/target interval.
For every source the newest *archived* issue at or before that cutoff is used.
Only complete pairs across ALL requested sources enter scores. Missing, invalid,
ambiguous or curtailed values never become zero. The expected schedule must be
declared before inspection: this module cannot certify archive provenance or
prevent a caller from deliberately supplying a cherry-picked schedule.

Returned dictionaries are JSON serializable (no NaN). Positive bias means
overprediction. Energy errors are in kWh. Results describe this paired archive;
interval counts, duration weights and energy totals measure forecast-task
exposure, not unique physical generation or independent statistical samples.
``supports_improvement`` is a bounded operational gate, not statistical proof
or a claim about future, seasonal or productive accuracy.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
import math
from typing import Iterable, Mapping
from zoneinfo import ZoneInfo

from .models import midpoint_lead_hours


def _utc(value: datetime | str) -> datetime:
    value = datetime.fromisoformat(value) if isinstance(value, str) else value
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _power(value: float | None) -> bool:
    return (value is not None and not isinstance(value, bool) and isinstance(value, (float, int))
            and math.isfinite(value) and value >= 0)


@dataclass(frozen=True)
class ForecastRecord:
    source: str
    issued_at: datetime
    start: datetime
    end: datetime
    inverter_id: str
    power_w: float | None

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("source must be nonempty")
        if not isinstance(self.inverter_id, str) or not self.inverter_id.strip():
            raise ValueError("inverter_id must be nonempty")
        for key in ("issued_at", "start", "end"):
            object.__setattr__(self, key, _utc(getattr(self, key)))
        if self.end <= self.start:
            raise ValueError("Forecast interval must have positive duration")

    @classmethod
    def from_dict(cls, value: Mapping) -> ForecastRecord:
        return cls(**value)

    def to_dict(self) -> dict:
        return {key: value.isoformat() if isinstance(value, datetime) else value
                for key, value in self.__dict__.items()}


@dataclass(frozen=True)
class ForecastAttempt:
    """An issued source/stage attempt, including an entirely absent curve."""
    source: str
    issued_at: datetime
    inverter_id: str

    def __post_init__(self) -> None:
        for value in (self.source, self.inverter_id):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("attempt source and inverter must be nonempty")
        object.__setattr__(self, "issued_at", _utc(self.issued_at))


@dataclass(frozen=True)
class ActualRecord:
    start: datetime
    end: datetime
    inverter_id: str
    power_w: float | None
    observed_at: datetime
    curtailed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.inverter_id, str) or not self.inverter_id.strip():
            raise ValueError("inverter_id must be nonempty")
        if not isinstance(self.curtailed, bool):
            raise ValueError("curtailed must be boolean")
        for key in ("start", "end", "observed_at"):
            object.__setattr__(self, key, _utc(getattr(self, key)))
        if self.end <= self.start:
            raise ValueError("Actual interval must have positive duration")

    @classmethod
    def from_dict(cls, value: Mapping) -> ActualRecord:
        return cls(**value)

    def to_dict(self) -> dict:
        return {key: value.isoformat() if isinstance(value, datetime) else value
                for key, value in self.__dict__.items()}


@dataclass(frozen=True)
class EvaluationWindow:
    cutoff: datetime
    start: datetime
    end: datetime
    inverter_id: str
    daylight: bool | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.inverter_id, str) or not self.inverter_id.strip():
            raise ValueError("inverter_id must be nonempty")
        for key in ("cutoff", "start", "end"):
            object.__setattr__(self, key, _utc(getattr(self, key)))
        if not self.cutoff <= self.start < self.end:
            raise ValueError("Window must be future to its declared cutoff")
        if self.daylight is not None and not isinstance(self.daylight, bool):
            raise ValueError("daylight must be explicit bool or unavailable")

    @classmethod
    def from_dict(cls, value: Mapping) -> EvaluationWindow:
        return cls(**value)

    def to_dict(self) -> dict:
        return {key: value.isoformat() if isinstance(value, datetime) else value
                for key, value in self.__dict__.items()}


def _metrics(rows: list[tuple[float, float, float]]) -> dict:
    """Rows are actual, forecast, duration hours; interval means are weighted."""
    if not rows:
        return {"count": 0, "mae_w": None, "rmse_w": None, "bias_w": None,
                "actual_energy_kwh": None, "forecast_energy_kwh": None, "energy_bias_kwh": None}
    duration = sum(hours for _, _, hours in rows)
    actual_energy = sum(actual * hours for actual, _, hours in rows) / 1000
    forecast_energy = sum(predicted * hours for _, predicted, hours in rows) / 1000
    return {"count": len(rows),
            "mae_w": sum(abs(predicted - actual) * hours for actual, predicted, hours in rows) / duration,
            "rmse_w": math.sqrt(sum((predicted - actual) ** 2 * hours for actual, predicted, hours in rows) / duration),
            "bias_w": sum((predicted - actual) * hours for actual, predicted, hours in rows) / duration,
            "actual_energy_kwh": actual_energy, "forecast_energy_kwh": forecast_energy,
            "energy_bias_kwh": forecast_energy - actual_energy}


def _energy_metrics(rows: list[tuple[float, float]]) -> dict:
    if not rows:
        return {"count": 0, "mae_kwh": None, "rmse_kwh": None, "bias_kwh": None}
    errors = [forecast - actual for actual, forecast in rows]
    return {"count": len(rows), "mae_kwh": sum(abs(x) for x in errors) / len(errors),
            "rmse_kwh": math.sqrt(sum(x * x for x in errors) / len(errors)),
            "bias_kwh": sum(errors) / len(errors)}


def _lead(hours: float) -> str:
    for boundary, label in ((6, "0-6h"), (24, "6-24h"), (48, "24-48h"), (96, "48-96h")):
        if hours < boundary:
            return label
    return "96h+"


def _interval_mean(rows: list, start: datetime, end: datetime, *, clip: bool = True) -> float | None:
    """Integrate fully covered interval means without interpolation over gaps.

    Forecast means are piecewise constant inside their archived intervals.
    Identical duplicates collapse, while any conflicting overlapping means
    remain ambiguous. This allows 15-minute measurements versus hourly curves.
    """
    pieces: dict[tuple, list] = defaultdict(list)
    for row in rows:
        if row.start < end and row.end > start:
            if not clip and (row.start < start or row.end > end):
                # An observed mean does not reveal energy in either edge
                # fragment. Only forecasts are piecewise-constant estimates.
                return None
            pieces[max(start, row.start), min(end, row.end)].append(row.power_w)
    cursor, integral = start, 0.0
    for (left, right), values in sorted(pieces.items()):
        if left != cursor or not all(_power(value) for value in values) or len(set(values)) != 1:
            return None
        integral += values[0] * (right - left).total_seconds()
        cursor = right
    return integral / (end - start).total_seconds() if cursor == end else None


def evaluate_forecasts(
    forecasts: Iterable[ForecastRecord],
    actuals: Iterable[ActualRecord],
    windows: Iterable[EvaluationWindow],
    *,
    as_of: datetime,
    forecast_attempts: Iterable[ForecastAttempt] = (),
    sources: tuple[str, ...] = ("adaptive", "physics", "helios", "open_meteo"),
    timezone_name: str = "UTC",
    min_coverage: float = 0.95,
    min_paired_days: int = 30,
    min_paired_intervals: int = 100,
    min_daily_win_fraction: float = 0.6,
    min_relative_improvement: float = 0.05,
    max_inverter_worsening: float = 0.02,
) -> dict:
    """Score exact interval means at common cutoffs with an explicit coverage gate.

    Daily/rest-day energy metrics require a continuous paired span from local
    midnight/cutoff to the next local midnight, including known zero nighttime
    intervals. DST days therefore have their actual 23/24/25-hour duration.
    Interval scores can still be reported descriptively below the claim gate.
    Explicit forecast_attempts retain empty newer curves in origin selection.
    An older valid issue never masks an unavailable newest archived issue.
    Lead groups use the declared common cutoff to the target-window midpoint,
    independent of each source's selected archived issue timestamp.
    The daily-win threshold applies separately to each declared inverter/horizon
    stratum. Repeated origins within one stratum/day use mean absolute energy
    error and count as one day only when every planned origin is paired. The
    minimum-day gate uses that same complete-origin denominator. The
    top-level daily_win_fraction is the minimum stratum fraction (null if any
    stratum has no complete day), never a pooled or weighted success fraction.
    """
    as_of, tz = _utc(as_of), ZoneInfo(timezone_name)
    sources = tuple(sources)
    if (not sources or len(set(sources)) != len(sources) or not 0 < min_coverage <= 1
            or min_paired_days < 1 or min_paired_intervals < 1
            or not 0.5 <= min_daily_win_fraction <= 1
            or not 0 <= min_relative_improvement < 1
            or not 0 <= max_inverter_worsening < 1):
        raise ValueError("Invalid evaluation policy")
    schedule = sorted(set(windows), key=lambda x: (x.cutoff, x.inverter_id, x.start, x.end))
    # Within one decision, overlaps double-weight the same forecast curve.
    # Different declared cutoffs are distinct tasks even for the same target.
    previous: dict[tuple, datetime] = {}
    for window in schedule:
        key = window.cutoff, window.inverter_id
        if key in previous and window.start < previous[key]:
            raise ValueError("Evaluation schedule contains overlapping intervals")
        previous[key] = window.end
    forecast_index: dict[tuple, dict[datetime, list[ForecastRecord]]] = defaultdict(lambda: defaultdict(list))
    for row in forecasts:
        if row.source in sources:
            forecast_index[row.source, row.inverter_id][row.issued_at].append(row)
    for attempt in forecast_attempts:
        if attempt.source in sources:
            forecast_index[attempt.source, attempt.inverter_id][attempt.issued_at]
    source_issues = {key: sorted(issues) for key, issues in forecast_index.items()}
    actual_index: dict[str, list[ActualRecord]] = defaultdict(list)
    for row in actuals:
        actual_index[row.inverter_id].append(row)
    paired = []
    excluded: Counter[str] = Counter()
    per_source_available = {source: 0 for source in sources}
    missing = []
    eligible = []
    for window in schedule:
        candidates = [row for row in actual_index[window.inverter_id]
                      if row.start < window.end and row.end > window.start
                      and row.end <= row.observed_at <= as_of]
        # Any curtailment observation invalidates the complete target interval.
        if any(row.curtailed for row in candidates):
            excluded["curtailed"] += 1
            continue
        eligible.append(window)
        actual = _interval_mean(candidates, window.start, window.end, clip=False)
        predictions = {}
        for source in sources:
            index_key = source, window.inverter_id
            issues = source_issues.get(index_key, [])
            position = bisect_right(issues, min(window.cutoff, window.start, as_of)) - 1
            if position < 0:
                continue
            latest = forecast_index[index_key][issues[position]]
            value = _interval_mean(latest, window.start, window.end)
            if value is not None:
                predictions[source] = value
                per_source_available[source] += 1
        if actual is None or len(predictions) != len(sources):
            excluded["missing_actual" if actual is None else "missing_forecast"] += 1
            missing.append({**window.to_dict(), "missing_actual": actual is None,
                            "missing_sources": [source for source in sources if source not in predictions]})
            continue
        paired.append((window, actual, predictions))
    paired_map = {(row.cutoff, row.start, row.end, row.inverter_id): (actual, values)
                  for row, actual, values in paired}
    expected_groups: dict[tuple, list[EvaluationWindow]] = defaultdict(list)
    # Curtailed windows stay in the energy schedule, so their removal cannot
    # silently turn a partly observed day into a complete daily total.
    for window in schedule:
        expected_groups[window.cutoff, window.start.astimezone(tz).date(), window.inverter_id].append(window)
    energies = []
    group_horizons = {}
    unsupported_energy_groups = 0
    for (cutoff, target_day, inverter), group in expected_groups.items():
        group.sort(key=lambda x: x.start)
        complete = all((row.cutoff, row.start, row.end, row.inverter_id) in paired_map for row in group)
        continuous = all(left.end == right.start for left, right in zip(group, group[1:]))
        midnight = datetime.combine(target_day, time(), tz).astimezone(timezone.utc)
        next_midnight = datetime.combine(target_day + timedelta(days=1), time(), tz).astimezone(timezone.utc)
        full_day = group[0].start == midnight and group[-1].end == next_midnight
        rest_day = (cutoff.astimezone(tz).date() == target_day
                    and group[0].start == cutoff and group[-1].end == next_midnight)
        if continuous and (full_day or rest_day):
            local_cutoff = cutoff.astimezone(tz)
            horizon = (f"day_{(target_day - local_cutoff.date()).days}_at_{local_cutoff:%H:%M}"
                       if full_day else f"rest_of_day_{local_cutoff:%H:%M}")
            group_horizons[cutoff, target_day, inverter] = horizon
        else:
            unsupported_energy_groups += 1
        if not complete or not continuous or not (full_day or rest_day):
            continue
        totals = {source: 0.0 for source in sources}
        actual_total = 0.0
        for row in group:
            actual, values = paired_map[row.cutoff, row.start, row.end, row.inverter_id]
            hours = (row.end - row.start).total_seconds() / 3600
            actual_total += actual * hours / 1000
            for source in sources:
                totals[source] += values[source] * hours / 1000
        energies.append({"cutoff": cutoff.isoformat(), "target_day": target_day.isoformat(),
                         "inverter_id": inverter, "kind": "day" if full_day else "rest_of_day",
                         "horizon": horizon,
                         "actual_kwh": actual_total, "forecasts_kwh": totals})
    scores = {}
    for source in sources:
        rows = [(window, (actual, values[source], (window.end - window.start).total_seconds() / 3600))
                for window, actual, values in paired]
        by_inverter: dict[str, list] = defaultdict(list)
        by_lead: dict[str, list] = defaultdict(list)
        by_horizon: dict[str, list] = defaultdict(list)
        by_inverter_lead: dict[tuple, list] = defaultdict(list)
        rest = []
        for window, metrics_row in rows:
            by_inverter[window.inverter_id].append(metrics_row)
            lead = _lead(midpoint_lead_hours(window.cutoff, window.start, window.end))
            by_lead[lead].append(metrics_row)
            by_inverter_lead[window.inverter_id, lead].append(metrics_row)
            horizon = group_horizons.get((window.cutoff, window.start.astimezone(tz).date(), window.inverter_id))
            if horizon is not None:
                by_horizon[horizon].append(metrics_row)
            if window.cutoff.astimezone(tz).date() == window.start.astimezone(tz).date():
                rest.append(metrics_row)
        scores[source] = {"overall": _metrics([row for _, row in rows]),
                          "by_inverter": {key: _metrics(value) for key, value in by_inverter.items()},
                          "by_lead": {key: _metrics(value) for key, value in by_lead.items()},
                          "by_inverter_lead": {f"{key[0]}|{key[1]}": _metrics(value)
                                               for key, value in by_inverter_lead.items()},
                          "by_horizon": {key: {**_metrics(value), "energy": _energy_metrics([
                              (x["actual_kwh"], x["forecasts_kwh"][source]) for x in energies if x["horizon"] == key])}
                              for key, value in by_horizon.items()},
                          "daylight_intervals": _metrics([row for window, row in rows if window.daylight is True]),
                          "night_intervals": _metrics([row for window, row in rows if window.daylight is False]),
                          "unclassified_intervals": sum(window.daylight is None for window, _ in rows),
                          "rest_of_day_intervals": _metrics(rest),
                          "daily_energy": _energy_metrics([(x["actual_kwh"], x["forecasts_kwh"][source])
                                                           for x in energies if x["kind"] == "day"]),
                          "rest_of_day_energy": _energy_metrics([(x["actual_kwh"], x["forecasts_kwh"][source])
                                                                 for x in energies if x["kind"] == "rest_of_day"])}
        for inverter, inverter_score in scores[source]["by_inverter"].items():
            inverter_score["daily_energy"] = _energy_metrics([
                (x["actual_kwh"], x["forecasts_kwh"][source]) for x in energies
                if x["kind"] == "day" and x["inverter_id"] == inverter])
            inverter_score["rest_of_day_energy"] = _energy_metrics([
                (x["actual_kwh"], x["forecasts_kwh"][source]) for x in energies
                if x["kind"] == "rest_of_day" and x["inverter_id"] == inverter])
    paired_seconds = sum((row.end - row.start).total_seconds() for row, _, _ in paired)
    eligible_seconds = sum((row.end - row.start).total_seconds() for row in eligible)
    coverage = paired_seconds / eligible_seconds if eligible_seconds else 0.0
    paired_days = len({window.start.astimezone(tz).date() for window, _, _ in paired})
    energy_days = len({x["target_day"] for x in energies if x["kind"] == "day"})
    complete_span_days = len({x["target_day"] for x in energies})
    reasons = []
    if coverage < min_coverage:
        reasons.append("insufficient_common_coverage")
    if paired_days < min_paired_days or complete_span_days < min_paired_days:
        reasons.append("insufficient_complete_paired_days")
    if len(paired) < min_paired_intervals:
        reasons.append("insufficient_paired_intervals")
    inverter_coverage = {}
    inverter_complete_days = {}
    for inverter in sorted({row.inverter_id for row in schedule}):
        expected_duration = sum((row.end - row.start).total_seconds()
                                for row in eligible if row.inverter_id == inverter)
        common_duration = sum((row.end - row.start).total_seconds()
                              for row, _, _ in paired if row.inverter_id == inverter)
        inverter_coverage[inverter] = common_duration / expected_duration if expected_duration else 0.0
        inverter_complete_days[inverter] = len({x["target_day"] for x in energies
                                                if x["inverter_id"] == inverter})
    if any(value < min_coverage for value in inverter_coverage.values()):
        reasons.append("insufficient_per_inverter_coverage")
    if any(value < min_paired_days for value in inverter_complete_days.values()):
        reasons.append("insufficient_per_inverter_complete_days")
    if unsupported_energy_groups:
        reasons.append("incomplete_declared_energy_schedule")
    strata = {}
    complete_days_by_stratum = {}
    for inverter, horizon in sorted({(inverter, horizon)
                                     for (_, _, inverter), horizon in group_horizons.items()}):
        scope_windows = [window for window in eligible if window.inverter_id == inverter
                         and group_horizons.get((window.cutoff, window.start.astimezone(tz).date(), inverter)) == horizon]
        expected_duration = sum((row.end - row.start).total_seconds() for row in scope_windows)
        common_duration = sum((row.end - row.start).total_seconds() for row in scope_windows
                              if (row.cutoff, row.start, row.end, row.inverter_id) in paired_map)
        energy_rows = [x for x in energies if x["inverter_id"] == inverter and x["horizon"] == horizon]
        expected_pairs = [
            {"cutoff": cutoff.isoformat(), "target_day": target_day.isoformat()}
            for (cutoff, target_day, group_inverter), group_horizon in sorted(group_horizons.items())
            if group_inverter == inverter and group_horizon == horizon]
        expected_origins = Counter(row["target_day"] for row in expected_pairs)
        paired_origins = Counter(row["target_day"] for row in energy_rows)
        complete_days = {day for day, count in expected_origins.items() if paired_origins[day] == count}
        key = f"{inverter}|{horizon}"
        complete_days_by_stratum[key] = complete_days
        strata[key] = {
            "inverter_id": inverter, "horizon": horizon,
            "expected_pairs": expected_pairs,
            "coverage": common_duration / expected_duration if expected_duration else 0.0,
            "complete_target_days": len(complete_days),
            "scores": {source: _energy_metrics([(x["actual_kwh"], x["forecasts_kwh"][source])
                                                 for x in energy_rows]) for source in sources}}
    if any(x["coverage"] < min_coverage for x in strata.values()):
        reasons.append("insufficient_per_horizon_inverter_coverage")
    if not strata or any(x["complete_target_days"] < min_paired_days for x in strata.values()):
        reasons.append("insufficient_per_horizon_inverter_days")
    improvement = {}
    if "adaptive" in sources:
        for source in sources:
            if source == "adaptive":
                continue
            # Preserve the declared family: a large inverter or overlapping
            # day/rest horizon cannot supply another stratum's daily wins.
            daily_errors: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
            for row in energies:
                key = f"{row['inverter_id']}|{row['horizon']}", row["target_day"]
                daily_errors[key].append((abs(row["forecasts_kwh"]["adaptive"] - row["actual_kwh"]),
                                          abs(row["forecasts_kwh"][source] - row["actual_kwh"])))
            adaptive_mae = scores["adaptive"]["overall"]["mae_w"]
            reference_mae = scores[source]["overall"]["mae_w"]
            horizon_checks = {}
            for horizon, metric in scores["adaptive"]["by_horizon"].items():
                candidate = metric["energy"]
                reference = scores[source]["by_horizon"][horizon]["energy"]
                horizon_checks[horizon] = bool(
                    candidate["mae_kwh"] is not None and reference["mae_kwh"] is not None
                    and reference["mae_kwh"] > 0
                    and candidate["mae_kwh"] <= reference["mae_kwh"] * (1 - min_relative_improvement) + 1e-12
                    and abs(candidate["bias_kwh"]) <= abs(reference["bias_kwh"]) + 1e-12)
            inverter_checks = {}
            daily_win_checks = {}
            daily_win_reasons = []
            for key, stratum in strata.items():
                candidate, reference = stratum["scores"]["adaptive"], stratum["scores"][source]
                inverter_checks[key] = bool(candidate["mae_kwh"] is not None and reference["mae_kwh"] is not None
                    and candidate["mae_kwh"] <= reference["mae_kwh"] * (1 + max_inverter_worsening) + 1e-12
                    and abs(candidate["bias_kwh"]) <= abs(reference["bias_kwh"]) + 1e-12)
                expected_days = Counter(row["target_day"] for row in stratum["expected_pairs"])
                day_means = []
                for day in sorted(complete_days_by_stratum[key]):
                    expected_count = expected_days[day]
                    errors = daily_errors[key, day]
                    day_means.append((sum(row[0] for row in errors) / expected_count,
                                      sum(row[1] for row in errors) / expected_count))
                wins = sum(candidate < reference for candidate, reference in day_means)
                fraction = wins / len(day_means) if day_means else None
                failures = []
                if fraction is None:
                    failures.append("no_complete_paired_target_days")
                else:
                    if len(day_means) < min_paired_days:
                        failures.append("insufficient_complete_paired_target_days")
                    if fraction < min_daily_win_fraction:
                        failures.append("insufficient_daily_win_fraction")
                passed = not failures
                daily_win_checks[key] = {"expected_target_days": len(expected_days),
                                         "paired_target_days": len(day_means), "winning_target_days": wins,
                                         "daily_win_fraction": fraction, "passed": passed,
                                         "gate_reasons": failures}
                daily_win_reasons.extend(f"{reason}:{key}" for reason in failures)
            fractions = [check["daily_win_fraction"] for check in daily_win_checks.values()]
            win_fraction = min(fractions) if fractions and all(value is not None for value in fractions) else None
            lead_checks = {key: metric["mae_w"] <= scores[source]["by_inverter_lead"][key]["mae_w"]
                           * (1 + max_inverter_worsening) + 1e-12
                           for key, metric in scores["adaptive"]["by_inverter_lead"].items()}
            improved = (not reasons and adaptive_mae is not None and reference_mae is not None
                        and adaptive_mae <= reference_mae
                        and bool(horizon_checks) and all(horizon_checks.values())
                        and all(inverter_checks.values()) and all(lead_checks.values())
                        and bool(daily_win_checks) and all(check["passed"] for check in daily_win_checks.values()))
            improvement[source] = {"supports_improvement_on_paired_archive": bool(improved),
                                   "daily_win_fraction": win_fraction,
                                   "daily_win_fraction_summary": "minimum_across_declared_inverter_horizon_strata",
                                   "daily_win_by_inverter_horizon": daily_win_checks,
                                   "daily_win_gate_reasons": daily_win_reasons, "by_horizon": horizon_checks,
                                   "by_inverter_horizon": inverter_checks, "by_inverter_lead": lead_checks}
    return {"evidence": "paired_archived_forecasts_only", "as_of": as_of.isoformat(),
            "sources": list(sources), "expected_intervals": len(schedule),
            "eligible_intervals": len(eligible), "paired_intervals": len(paired),
            "paired_target_days": paired_days, "complete_daily_target_days": energy_days,
            "per_inverter_coverage": inverter_coverage,
            "per_inverter_complete_days": inverter_complete_days,
            "strata": strata, "statistical_acceptance": "not_evaluated",
            "coverage": coverage, "interval_count_coverage": len(paired) / len(eligible) if eligible else 0.0,
            "source_available_intervals": per_source_available,
            "excluded": dict(excluded), "missing": missing, "scores": scores,
            "energy_pairs": energies, "comparison_eligible": not reasons,
            "supports_improvement_over_both_references_on_paired_archive": bool(
                all(reference in improvement for reference in ("helios", "open_meteo"))
                and all(improvement[reference]["supports_improvement_on_paired_archive"]
                        for reference in ("helios", "open_meteo"))),
            "gate_reasons": reasons, "improvement": improvement,
            "policy": {"min_coverage": min_coverage, "min_paired_days": min_paired_days,
                       "interval_task_identity": ["cutoff", "inverter_id", "start", "end"],
                       "interval_count_scope": "declared_forecast_tasks_not_independent_samples",
                       "interval_weighting": "forecast_task_duration_hours",
                       "interval_energy_scope": "forecast_task_exposure_not_unique_generation",
                       "lead_reference": "declared_cutoff_to_target_interval_midpoint",
                       "min_paired_intervals": min_paired_intervals,
                       "min_daily_win_fraction": min_daily_win_fraction,
                       "daily_win_scope": "each_declared_inverter_horizon_stratum",
                       "complete_target_day_scope": "all_declared_origins_within_inverter_horizon_stratum",
                       "min_relative_improvement": min_relative_improvement,
                       "max_inverter_worsening": max_inverter_worsening}}
