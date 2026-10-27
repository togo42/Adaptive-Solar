"""Small chronological bias candidate, recorded in shadow and never published.

One bounded, regularized gain per stage/regime/lead bin deliberately has far
less capacity than the residual trees. A successful internal holdout makes it
eligible for prospective comparison, not for automatic operational activation.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from statistics import median
from zoneinfo import ZoneInfo

import numpy as np

from .learning import (
    LEAD_BIN_NAMES, Prediction, _input_rejection, _target_hours, _valid_output_cap,
    _valid_shade_factor, _vector, _weights, feature_regime, lead_bin,
)
from .models import TrainingSample, finite_number, utc_time
from .shading import feature_shade_bin, shade_factors_compatible

MIN_BIAS_DAYS = 14
MIN_BIAS_HOURS = 48
MIN_BIAS_VALIDATION_DAYS = 3
MIN_BIAS_VALIDATION_HOURS = 12
MAX_BIAS_GAIN_DEVIATION = 0.20


class EarlyBiasShadow:
    """A fixed low-capacity policy whose validation labels never fit its gain."""

    def __init__(self, *, timezone_name: str = "UTC", output_caps=None):
        self.timezone = ZoneInfo(timezone_name)
        self.output_caps = {key: finite_number(value, "output cap", 1e-6)
                            for key, value in (output_caps or {}).items()}
        self.status: dict = {}
        self._models: dict = {}
        self.evaluated_at: str | None = None

    def fit(self, samples, as_of: datetime):
        as_of = utc_time(as_of)
        self.evaluated_at = as_of.isoformat()
        self.status, self._models = {}, {}
        unique = defaultdict(list)
        for row in samples:
            if not isinstance(row, TrainingSample):
                continue
            cap = _valid_output_cap(row.features, self.output_caps.get(row.inverter_id))
            if _input_rejection(row, as_of, _vector(row.features), _valid_shade_factor(row.features), cap):
                continue
            # Low-power ratios are unstable; finite configured/archived caps are
            # required for the candidate even for legacy caller rows.
            if (cap is None or not np.isfinite(cap) or row.baseline_w < cap * 0.05
                    or feature_shade_bin(row.features) is None):
                continue
            unique[row.inverter_id, feature_regime(row.features), row.issued_at, row.start, row.end].append(row)
        rows = [values[0] for values in unique.values() if all(row == values[0] for row in values)]
        labels = defaultdict(set)
        for row in rows:
            labels[row.inverter_id, row.start, row.end].add(row.actual_w)
        groups = defaultdict(list)
        for row in rows:
            if len(labels[row.inverter_id, row.start, row.end]) == 1:
                groups[row.inverter_id, feature_regime(row.features), lead_bin(row.features["lead_hours"])].append(row)
        for key, group in sorted(groups.items()):
            self._fit_group(key, group)
        return self

    def _day(self, row):
        return row.start.astimezone(self.timezone).date()

    def _fit_group(self, key, rows):
        inverter, regime, index = key
        days = sorted({self._day(row) for row in rows})
        report = {"state": "insufficient_history", "target_days": len(days),
                  "unique_target_hours": _target_hours(rows), "operational_use": False,
                  "policy": "early-bias-shadow-v1"}
        stage = self.status.setdefault(inverter, {"operational_use": False, "regimes": {}})
        stage["regimes"].setdefault(regime, {})[LEAD_BIN_NAMES[index]] = report
        if len(days) < MIN_BIAS_DAYS or report["unique_target_hours"] < MIN_BIAS_HOURS:
            return
        edge = days[-max(MIN_BIAS_VALIDATION_DAYS, len(days) // 5)]
        validation = sorted((row for row in rows if self._day(row) >= edge), key=lambda row: row.start)
        first_issue = min(row.issued_at for row in validation)
        first_target = min(row.start for row in validation)
        train = [row for row in rows if self._day(row) < edge and row.end <= first_target
                 and row.observed_at <= first_issue]
        report.update(train_target_days=len({self._day(row) for row in train}),
                      train_target_hours=_target_hours(train), validation_start=edge.isoformat(),
                      validation_target_hours=_target_hours(validation))
        if report["train_target_days"] < 7 or report["train_target_hours"] < 24:
            report["state"] = "insufficient_causal_training"
            return
        if report["validation_target_hours"] < MIN_BIAS_VALIDATION_HOURS:
            return
        lower_lead = max(min(r.features["lead_hours"] for r in train), min(r.features["lead_hours"] for r in validation))
        upper_lead = min(max(r.features["lead_hours"] for r in train), max(r.features["lead_hours"] for r in validation))
        train = [r for r in train if lower_lead <= r.features["lead_hours"] <= upper_lead]
        validation = [r for r in validation if lower_lead <= r.features["lead_hours"] <= upper_lead]
        report.update(train_target_days=len({self._day(r) for r in train}),
                      train_target_hours=_target_hours(train),
                      validation_target_days=len({self._day(r) for r in validation}),
                      validation_target_hours=_target_hours(validation))
        if (_target_hours(train) < 24 or _target_hours(validation) < MIN_BIAS_VALIDATION_HOURS
                or len({self._day(r) for r in train}) < 7
                or len({self._day(r) for r in validation}) < MIN_BIAS_VALIDATION_DAYS):
            report["state"] = "insufficient_lead_support"
            return
        # Validate the exact same shade baseline phase in both blocks. A gain
        # must not silently compensate a newly released shade correction.
        trained_shade, validated_shade = defaultdict(list), defaultdict(list)
        for block, destination in ((train, trained_shade), (validation, validated_shade)):
            for row in block:
                destination[feature_shade_bin(row.features)].append(float(row.features.get("beam_shade_factor", 1)))
        shade = {}
        for window, values in trained_shade.items():
            others = validated_shade.get(window)
            if others and all(shade_factors_compatible(value, others[-1]) for value in values + others):
                shade[window] = others[-1]
        if any(feature_shade_bin(r.features) not in shade for r in train + validation):
            report["state"] = "incompatible_shade_support"
            return
        ratios = []
        for day in sorted({self._day(row) for row in train}):
            daily = [row for row in train if self._day(row) == day]
            weights = _weights(daily)
            ratios.append(float(np.dot(weights, [r.actual_w for r in daily])
                                / np.dot(weights, [r.baseline_w for r in daily])))
        raw_gain = max(1 - MAX_BIAS_GAIN_DEVIATION, min(1 + MAX_BIAS_GAIN_DEVIATION, median(ratios)))
        # Seven neutral prior days reduce the influence of a short first corpus.
        gain = 1 + (raw_gain - 1) * len(ratios) / (len(ratios) + 7)
        actual = np.array([r.actual_w for r in validation])
        base = np.array([r.baseline_w for r in validation])
        caps = np.array([_valid_output_cap(r.features, self.output_caps.get(inverter)) for r in validation])
        predicted = np.minimum(caps, base * gain)
        weights = _weights(validation)
        baseline_mae = float(np.average(np.abs(actual - base), weights=weights))
        candidate_mae = float(np.average(np.abs(actual - predicted), weights=weights))
        wins = []
        for day in sorted({self._day(row) for row in validation}):
            mask = np.array([self._day(row) == day for row in validation])
            wins.append(float(np.average(np.abs(actual[mask] - predicted[mask]), weights=weights[mask]))
                        < float(np.average(np.abs(actual[mask] - base[mask]), weights=weights[mask])))
        report.update(gain=gain, physics_validation_mae_w=baseline_mae,
                      candidate_validation_mae_w=candidate_mae,
                      validation_daily_win_fraction=sum(wins) / len(wins),
                      supported_lead_min_hours=lower_lead, supported_lead_max_hours=upper_lead,
                      causal_observation_cutoff=first_issue.isoformat(),
                      latest_training_observed_at=max(row.observed_at for row in train).isoformat(),
                      train_end=max(self._day(row) for row in train).isoformat(),
                      validation_end=max(self._day(row) for row in validation).isoformat())
        if baseline_mae <= 0 or candidate_mae >= baseline_mae * 0.95 or sum(wins) / len(wins) < 0.6:
            report["state"] = "rejected_validation"
            return
        report["state"] = "shadow_ready"
        self._models[key] = gain, lower_lead, upper_lead, shade

    def predict(self, inverter_id, features, baseline_w, cap_w):
        baseline_w = finite_number(baseline_w, "baseline", 0)
        cap_w = finite_number(cap_w, "cap", 1e-6)
        fallback = Prediction(min(cap_w, baseline_w), status="physics_shadow_unavailable")
        if _vector(features) is None or _valid_shade_factor(features) is None:
            return fallback
        if _valid_output_cap(features, self.output_caps.get(inverter_id, cap_w)) != cap_w:
            return fallback
        if baseline_w < cap_w * 0.05 or features["baseline_w"] != baseline_w:
            return fallback
        fitted = self._models.get((inverter_id, feature_regime(features), lead_bin(features["lead_hours"])))
        if fitted is None:
            return fallback
        gain, low, high, shade = fitted
        window = feature_shade_bin(features)
        if (not low <= features["lead_hours"] <= high or window not in shade
                or not shade_factors_compatible(features.get("beam_shade_factor", 1), shade[window])):
            return fallback
        return Prediction(min(cap_w, baseline_w * gain), status="shadow_bias_candidate")
