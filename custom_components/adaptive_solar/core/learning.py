"""Conservative, per-inverter residual learning from archived forecast features.

``ResidualLearner().fit(samples, as_of)`` reconstructs models from JSON-safe
TrainingSample rows; executable model serializations are deliberately unnecessary.
The model sees target-day chronological train / validation / calibration blocks.
It is never refitted on its validation or calibration labels. Validation is an
internal activation check, not evidence of superiority over another integration.
Repeated forecast issues receive a total weight of one per measured interval.
Empirical absolute-error bounds describe the held-out calibration archive only;
they are not a guarantee of future coverage or conditional P10/P90 estimates.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Iterable, Mapping
from zoneinfo import ZoneInfo

import numpy as np
from sklearn.ensemble import GradientBoostingRegressor

from .models import TrainingSample

MIN_TRAINING_SECONDS = 0.95 * 1800
MIN_MEASUREMENT_COVERAGE = 0.95
MAX_MEASUREMENT_EDGE_FRACTION = 0.025

FEATURE_NAMES = (
    "baseline_w", "sun_elevation_deg", "sun_azimuth_sin", "sun_azimuth_cos",
    "day_of_year_sin", "day_of_year_cos", "temperature_c", "wind_m_s",
    "cloud_cover_pct", "lead_hours",
    "ghi_nowcast_gain", "ghi_observation_age_seconds", "ghi_regime",
)
LEAD_FEATURE_INDEX = FEATURE_NAMES.index("lead_hours")
LEAD_BIN_NAMES = ("0-6h", "6-24h", "24-48h", "48-96h", "96h+")


def lead_bin(lead_hours: float) -> int:
    """Same numeric boundaries as coordinator archive arms, without HA imports."""
    return next((index for index, boundary in enumerate((6, 24, 48, 96))
                 if lead_hours < boundary), 4)


def _target_hours(rows: list[TrainingSample]) -> int:
    """Whole hours of unique observed duration, never one vote per tiny piece."""
    merged = []
    for start, end in sorted({(row.start, row.end) for row in rows}):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return int(sum((end - start).total_seconds() for start, end in merged) // 3600)


def _aligned_duration(row: TrainingSample) -> bool:
    duration = (row.end - row.start).total_seconds()
    target = row.features.get("target_duration_seconds", duration)
    coverage = row.features.get("measurement_coverage_fraction", 1.0)
    edge = row.features.get("measurement_edge_fraction", 0.0)
    return (duration >= MIN_TRAINING_SECONDS and target >= 1800
            and MIN_MEASUREMENT_COVERAGE <= coverage <= 1.0
            and 0 <= edge <= MAX_MEASUREMENT_EDGE_FRACTION
            and math.isclose(duration / target, coverage, rel_tol=1e-9, abs_tol=1e-9))


@dataclass(frozen=True)
class Prediction:
    power_w: float
    lower_w: float | None = None
    upper_w: float | None = None
    status: str = "physics_cold_start"


def _aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def ghi_feature_values(features: Mapping[str, float]) -> dict[str, float] | None:
    """Explicit regimes, with conservative backward-compatible archive defaults.

    Legacy rows without any GHI marker are NWP. Legacy applied-GHI rows already
    carry gain AND age; these may be classified as GHI, never silently as NWP.
    An incomplete or contradictory marker set fails closed.
    """
    markers = {"ghi_nowcast_gain", "ghi_observation_age_seconds", "ghi_observation_w_m2"}
    explicit = features.get("ghi_regime")
    if explicit is None:
        regime = 1 if markers.intersection(features) else 0
    else:
        if isinstance(explicit, bool) or explicit not in (0, 1):
            return None
        regime = int(explicit)
    if regime and not {"ghi_nowcast_gain", "ghi_observation_age_seconds"} <= set(features):
        return None
    gain = features.get("ghi_nowcast_gain", 1.0)
    age = features.get("ghi_observation_age_seconds", 0.0)
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in (gain, age)):
        return None
    if not 0.35 <= gain <= 1.65 or not 0 <= age <= 300:
        return None
    if regime == 0 and (gain != 1 or age != 0 or "ghi_observation_w_m2" in features):
        return None
    return {"ghi_nowcast_gain": float(gain), "ghi_observation_age_seconds": float(age), "ghi_regime": float(regime)}


def feature_regime(features: Mapping[str, float]) -> str | None:
    values = ghi_feature_values(features)
    return None if values is None else "ghi" if values["ghi_regime"] else "nwp"


def _vector(features: Mapping[str, float]) -> list[float] | None:
    ghi = ghi_feature_values(features)
    if ghi is None:
        return None
    values = {**features, **ghi}
    try:
        row = [float(values[name]) for name in FEATURE_NAMES]
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    return row if all(math.isfinite(value) for value in row) else None


def _weights(rows: list[TrainingSample]) -> np.ndarray:
    counts = Counter((row.start, row.end, row.inverter_id) for row in rows)
    return np.array([(row.end - row.start).total_seconds()
                     / counts[row.start, row.end, row.inverter_id] for row in rows])


def _mae(actual: np.ndarray, predicted: np.ndarray, weights: np.ndarray) -> float:
    return float(np.average(np.abs(actual - predicted), weights=weights))


class ResidualLearner:
    """Gradient boosted residuals gated against physics on independent days.

    ``min_days`` counts unique target dates in ``timezone_name``. Defaults need
    28 days, 240 distinct UTC target hours, and four days in each held-out block.
    Interval duration weights prevent frequent energy-meter samples from
    outweighing slower meters or duplicate forecast origins.
    Unknown/missing features, night, curtailment and future labels are excluded.
    Training validity also requires that an issue predates the target interval
    and that its observation was finalized after the interval ended.
    Each lead bin additionally needs four independent validation days, 24 target
    hours in both training and validation, and the same improvement/win gate.
    Calibration bounds require four independent calibration days and 30 target
    hours in that specific bin. NWP and applied-GHI regimes have independent
    models, chronological gates, lead ranges and calibration. Neither regime
    activates or calibrates the other; legacy marker-free rows remain NWP.
    """

    def __init__(
        self,
        *,
        timezone_name: str = "UTC",
        min_days: int = 28,
        min_samples: int = 240,
        min_holdout_days: int = 4,
        min_bin_target_hours: int = 24,
        min_improvement: float = 0.05,
        min_daily_win_fraction: float = 0.6,
        calibration_coverage: float = 0.9,
    ) -> None:
        if min_days < 7 or min_samples < 12 or min_holdout_days < 1 or min_bin_target_hours < 12:
            raise ValueError("Insufficient minimum history configuration")
        if not 0 <= min_improvement < 1 or not 0.5 <= min_daily_win_fraction <= 1:
            raise ValueError("Invalid activation threshold")
        if not 0 < calibration_coverage < 1:
            raise ValueError("Invalid calibration coverage")
        self.timezone = ZoneInfo(timezone_name)
        self.min_days = min_days
        self.min_samples = min_samples
        self.min_holdout_days = min_holdout_days
        self.min_bin_target_hours = min_bin_target_hours
        self.min_improvement = min_improvement
        self.min_daily_win_fraction = min_daily_win_fraction
        self.calibration_coverage = calibration_coverage
        self._models: dict[tuple[str, str], tuple[GradientBoostingRegressor, dict[int, tuple[float | None, float, float]]]] = {}
        self.status: dict[str, dict] = {}
        self._regime_status: dict[str, dict[str, dict]] = {}

    def fit(self, samples: Iterable[TrainingSample], as_of: datetime) -> ResidualLearner:
        """Rebuild only from finalized labels available at ``as_of``.

        Ambiguous duplicate issues (same issue/interval, different features or
        label) are dropped together. A target with conflicting actual values
        across issues is dropped altogether, rather than selecting a lucky row.
        Whole targets belong to their local start date, including UTC hours
        crossing local midnight. Earlier blocks purge targets overlapping the
        next block's actual support; measured energy is never split.
        """
        if not _aware(as_of):
            raise ValueError("as_of must be timezone-aware")
        as_of = as_of.astimezone(timezone.utc)
        self._models.clear()
        self.status.clear()
        self._regime_status.clear()
        groups: dict[str, list[TrainingSample]] = defaultdict(list)
        rejected: Counter[str] = Counter()
        rejected_regimes: Counter[tuple[str, str | None]] = Counter()
        for row in samples:
            groups[row.inverter_id]  # Keep diagnostics even if every row is rejected.
            vector = _vector(row.features)
            valid = (
                all(_aware(t) for t in (row.issued_at, row.start, row.end, row.observed_at))
                and row.issued_at <= row.start < row.end <= row.observed_at <= as_of
                and _aligned_duration(row)
                and not row.curtailed and vector is not None
                and math.isfinite(row.baseline_w) and math.isfinite(row.actual_w)
                and row.baseline_w > 0 and row.actual_w >= 0
                and row.features.get("sun_elevation_deg", 0) > 0
                and row.features["lead_hours"] >= 0
                and math.isclose(row.features["baseline_w"], row.baseline_w, rel_tol=1e-8, abs_tol=1e-6)
            )
            if valid:
                groups[row.inverter_id].append(row)
            else:
                rejected[row.inverter_id] += 1
                rejected_regimes[row.inverter_id, feature_regime(row.features)] += 1
        for inverter, raw_rows in groups.items():
            issues: dict[tuple, list[TrainingSample]] = defaultdict(list)
            for row in raw_rows:
                issues[row.issued_at, row.start, row.end].append(row)
            rows = []
            for duplicates in issues.values():
                first = duplicates[0]
                if all(row.actual_w == first.actual_w and row.baseline_w == first.baseline_w
                       and row.features == first.features for row in duplicates):
                    rows.append(first)
            labels: dict[tuple, set[float]] = defaultdict(set)
            for row in rows:
                labels[row.start, row.end].add(row.actual_w)
            rows = [row for row in rows if len(labels[row.start, row.end]) == 1]
            rows.sort(key=lambda row: (row.start, row.end, row.issued_at))
            self._regime_status[inverter] = {}
            for regime in ("nwp", "ghi"):
                self._fit_regime(inverter, regime, [row for row in rows if feature_regime(row.features) == regime], rejected_regimes[inverter, regime])
            regimes = self._regime_status[inverter]
            # Flat validation metrics and lead bins belong to ONE explicitly
            # named regime. Prefer active NWP deterministically, then active
            # GHI; an inactive NWP report must not inherit GHI's active state.
            active = [name for name in ("nwp", "ghi") if regimes[name]["state"] == "active"]
            if active:
                primary = active[0]
            else:
                primary = "nwp" if not rows or any(feature_regime(row.features) == "nwp" for row in rows) else "ghi"
            report = {**regimes[primary], "primary_regime": primary, "active_regimes": active,
                      "regimes": regimes, "history_scope": "deduplicated_all_regimes",
                      "target_days": len({row.start.astimezone(self.timezone).date() for row in rows}),
                      "unique_intervals": len({(row.start, row.end) for row in rows}),
                      "unique_target_hours": _target_hours(rows), "issues": len(rows), "rejected_rows": rejected[inverter]}
            self.status[inverter] = report
        return self

    def _fit_regime(self, inverter: str, regime: str, rows: list[TrainingSample], rejected: int) -> None:
        def day(row: TrainingSample):
            return row.start.astimezone(self.timezone).date()
        dates = sorted({day(row) for row in rows})
        unique = len({(row.start, row.end) for row in rows})
        target_hours = _target_hours(rows)
        report = {"state": "insufficient_history", "target_days": len(dates),
                  "unique_intervals": unique, "unique_target_hours": target_hours,
                  "issues": len(rows), "rejected_rows": rejected,
                  "evidence": "internal_chronological_validation"}
        self._regime_status[inverter][regime] = report
        if len(dates) < self.min_days or target_hours < self.min_samples:
            return
        n_holdout = max(self.min_holdout_days, len(dates) // 5)
        if len(dates) - 2 * n_holdout < 3:
            return
        validation_start, calibration_start = dates[-2 * n_holdout], dates[-n_holdout]
        train = [row for row in rows if day(row) < validation_start]
        validation = [row for row in rows if validation_start <= day(row) < calibration_start]
        calibration = [row for row in rows if day(row) >= calibration_start]
        # Start-date grouping alone is insufficient for overlapping source
        # rasters. Keep each target whole and forbid shared label support at
        # both holdout boundaries, also in fractional-offset/DST timezones.
        validation_edge = min(row.start for row in validation)
        calibration_edge = min(row.start for row in calibration)
        train = [row for row in train if row.end <= validation_edge]
        validation = [row for row in validation if row.end <= calibration_edge]
        kept = train + validation + calibration
        report["purged_boundary_overlap_rows"] = len(rows) - len(kept)
        if len(kept) != len(rows):
            report.update(target_days=len({day(row) for row in kept}),
                          unique_intervals=len({(row.start, row.end) for row in kept}),
                          unique_target_hours=_target_hours(kept), issues=len(kept))
            if report["target_days"] < self.min_days or report["unique_target_hours"] < self.min_samples:
                return
        report.update(train_end=dates[-2 * n_holdout - 1].isoformat(),
                      validation_start=validation_start.isoformat(),
                      validation_end=dates[-n_holdout - 1].isoformat(),
                      calibration_start=calibration_start.isoformat(),
                      calibration_end=dates[-1].isoformat())
        if any(len({(row.start, row.end) for row in block}) < 12
               for block in (train, validation, calibration)):
            return
        model = GradientBoostingRegressor(
            n_estimators=100, learning_rate=0.05, max_depth=3,
            min_samples_leaf=8, loss="huber", random_state=0,
        )
        model.fit([_vector(row.features) for row in train],
                  [row.actual_w - row.baseline_w for row in train], sample_weight=_weights(train))
        baseline = np.array([row.baseline_w for row in validation])
        actual = np.array([row.actual_w for row in validation])
        predicted = np.maximum(0, baseline + model.predict([_vector(row.features) for row in validation]))
        weights = _weights(validation)
        baseline_mae, model_mae = _mae(actual, baseline, weights), _mae(actual, predicted, weights)
        wins = []
        for target_day in sorted({day(row) for row in validation}):
            mask = np.array([day(row) == target_day for row in validation])
            wins.append(_mae(actual[mask], predicted[mask], weights[mask])
                        < _mae(actual[mask], baseline[mask], weights[mask]))
        win_fraction = sum(wins) / len(wins)
        report.update(physics_validation_mae_w=baseline_mae, residual_validation_mae_w=model_mae,
                      validation_daily_win_fraction=win_fraction)
        if (not np.all(np.isfinite(predicted)) or baseline_mae <= 0
                or model_mae >= baseline_mae * (1 - self.min_improvement)
                or win_fraction < self.min_daily_win_fraction):
            report["state"] = "rejected_validation"
            return
        supported: dict[int, tuple[float | None, float, float]] = {}
        bin_reports = {}
        report["lead_bins"] = bin_reports
        for index, name in enumerate(LEAD_BIN_NAMES):
            train_rows = [row for row in train if lead_bin(row.features["lead_hours"]) == index]
            bin_rows = [row for row in validation if lead_bin(row.features["lead_hours"]) == index]
            lead_min = lead_max = None
            if train_rows and bin_rows:
                lead_min = max(min(row.features["lead_hours"] for row in train_rows), min(row.features["lead_hours"] for row in bin_rows))
                lead_max = min(max(row.features["lead_hours"] for row in train_rows), max(row.features["lead_hours"] for row in bin_rows))
                train_rows = [row for row in train_rows if lead_min <= row.features["lead_hours"] <= lead_max]
                bin_rows = [row for row in bin_rows if lead_min <= row.features["lead_hours"] <= lead_max]
            bin_report = {"state": "insufficient_validation", "train_target_hours": _target_hours(train_rows),
                          "train_target_days": len({day(row) for row in train_rows}),
                          "validation_target_hours": _target_hours(bin_rows),
                          "validation_target_days": len({day(row) for row in bin_rows})}
            bin_reports[name] = bin_report
            if (bin_report["train_target_hours"] < self.min_bin_target_hours
                    or bin_report["validation_target_hours"] < self.min_bin_target_hours
                    or bin_report["train_target_days"] < self.min_holdout_days
                    or bin_report["validation_target_days"] < self.min_holdout_days):
                continue
            mask = np.array([lead_bin(row.features["lead_hours"]) == index and lead_min <= row.features["lead_hours"] <= lead_max for row in validation])
            bin_weights = _weights(bin_rows)
            bin_actual, bin_baseline, bin_predicted = actual[mask], baseline[mask], predicted[mask]
            physics_mae = _mae(bin_actual, bin_baseline, bin_weights)
            residual_mae = _mae(bin_actual, bin_predicted, bin_weights)
            bin_wins = []
            for target_day in sorted({day(row) for row in bin_rows}):
                day_mask = np.array([day(row) == target_day for row in bin_rows])
                bin_wins.append(_mae(bin_actual[day_mask], bin_predicted[day_mask], bin_weights[day_mask])
                                < _mae(bin_actual[day_mask], bin_baseline[day_mask], bin_weights[day_mask]))
            bin_win_fraction = sum(bin_wins) / len(bin_wins)
            bin_report.update(physics_validation_mae_w=physics_mae, residual_validation_mae_w=residual_mae,
                              validation_daily_win_fraction=bin_win_fraction)
            if (physics_mae <= 0 or residual_mae >= physics_mae * (1 - self.min_improvement)
                    or bin_win_fraction < self.min_daily_win_fraction
                    or not np.all(np.isfinite(bin_predicted))):
                bin_report["state"] = "rejected_validation"
                continue
            # One deterministic issue per measured target *within this bin*.
            # Repeated issues cannot inflate the number of calibration labels.
            targets: dict[tuple, TrainingSample] = {}
            for row in calibration:
                if lead_bin(row.features["lead_hours"]) == index and lead_min <= row.features["lead_hours"] <= lead_max:
                    targets.setdefault((row.start, row.end), row)
            bin_calibration = list(targets.values())
            calibration_hours = _target_hours(bin_calibration)
            calibration_days = len({day(row) for row in bin_calibration})
            radius = None
            if calibration_hours >= 30 and calibration_days >= self.min_holdout_days:
                errors = np.abs(np.array([row.actual_w for row in bin_calibration]) - np.maximum(
                    0, np.array([row.baseline_w for row in bin_calibration])
                    + model.predict([_vector(row.features) for row in bin_calibration])))
                if np.all(np.isfinite(errors)):
                    order = np.argsort(errors)
                    duration_weights = _weights(bin_calibration)[order]
                    cumulative = np.cumsum(duration_weights) / duration_weights.sum()
                    radius = float(errors[order[min(len(order) - 1,
                                                  int(np.searchsorted(cumulative, self.calibration_coverage)))]])
            # The range and activation scores above both use the independent
            # train/validation intersection, never the whole named lead bin.
            supported[index] = (radius, lead_min, lead_max)
            bin_report.update(state="active", supported_lead_min_hours=lead_min, supported_lead_max_hours=lead_max, calibration_unique_intervals=len(bin_calibration),
                              calibration_target_hours=calibration_hours, calibration_target_days=calibration_days,
                              calibration_radius_w=radius,
                              uncertainty="empirical_calibration_absolute_error" if radius is not None else "unavailable",
                              nominal_calibration_coverage=self.calibration_coverage if radius is not None else None)
        if supported:
            self._models[inverter, regime] = (model, supported)
            report.update(state="active", uncertainty="per_lead_bin_empirical_calibration")
        else:
            report["state"] = "insufficient_lead_validation"

    def predict(self, inverter_id: str, features: Mapping[str, float], baseline_w: float, cap_w: float) -> Prediction:
        """Return bounded finite power; unknown models safely retain physics."""
        if not math.isfinite(cap_w) or cap_w < 0:
            raise ValueError("cap_w must be finite and nonnegative")
        if not math.isfinite(baseline_w) or baseline_w < 0:
            raise ValueError("baseline_w must be finite and nonnegative")
        fallback_w = min(baseline_w, cap_w)
        vector = _vector(features)
        if baseline_w == 0:
            return Prediction(0.0, status="physics_night")
        if (vector is None or vector[LEAD_FEATURE_INDEX] < 0
                or not math.isclose(vector[0], baseline_w, rel_tol=1e-8, abs_tol=1e-6)):
            return Prediction(fallback_w, status="physics_invalid_features")
        if vector[1] <= 0:
            return Prediction(0.0, status="physics_night")
        regime = feature_regime(features)
        fitted = self._models.get((inverter_id, regime))
        if fitted is None:
            reason = self._regime_status.get(inverter_id, {}).get(regime, {}).get("state", "cold_start")
            # Existing NWP-only callers keep their status strings. A missing
            # opposite regime is explicit even when another regime is active.
            other_active = any(key[0] == inverter_id for key in self._models)
            prefix = "physics_regime_" if other_active else "physics_"
            return Prediction(fallback_w, status=f"{prefix}{reason}")
        model, supported = fitted
        index = lead_bin(vector[LEAD_FEATURE_INDEX])
        if index not in supported:
            reason = self._regime_status[inverter_id][regime]["lead_bins"][LEAD_BIN_NAMES[index]]["state"]
            return Prediction(fallback_w, status=f"physics_lead_{reason}")
        radius, lead_min, lead_max = supported[index]
        if not lead_min <= vector[LEAD_FEATURE_INDEX] <= lead_max:
            return Prediction(fallback_w, status="physics_lead_outside_validated_range")
        value = baseline_w + float(model.predict([vector])[0])
        if not math.isfinite(value):
            return Prediction(fallback_w, status="physics_nonfinite_model")
        value = min(cap_w, max(0.0, value))
        return Prediction(value, max(0.0, value - radius) if radius is not None else None,
                          min(cap_w, value + radius) if radius is not None else None,
                          "residual_empirical_calibration" if radius is not None else "residual_no_uncertainty")
