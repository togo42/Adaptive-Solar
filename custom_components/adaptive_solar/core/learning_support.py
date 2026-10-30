"""Offline residual support candidate; never wired into the HA coordinator.

The original learner owns all quality, chronology, activation and shade gates.
Only its accepted training block supplies support. No validation/calibration
feature, label or error is used to select this candidate's thresholds. A support
check is not a sensor-health or concept-drift detector and proves no accuracy.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math

import numpy as np

from .learning import (
    FEATURE_NAMES, LEAD_BIN_NAMES, Prediction, ResidualLearner, _target_hours,
    _vector, _weights, feature_regime, lead_bin,
)

# Practical resolution floors are declared before looking at evaluation data.
# Circular sine/cosine pairs are assessed together, never by marginal min/max.
LINEAR_FLOORS = {
    "baseline_w": 20.0, "sun_elevation_deg": 2.0, "temperature_c": 2.0,
    "wind_m_s": 0.5, "cloud_cover_pct": 5.0, "lead_hours": 0.25,
    "ghi_nowcast_gain": 0.05, "ghi_observation_age_seconds": 30.0,
}
LINEAR_NAMES = tuple(LINEAR_FLOORS)
LINEAR_INDICES = tuple(FEATURE_NAMES.index(name) for name in LINEAR_NAMES)
CIRCULAR_PAIRS = tuple((FEATURE_NAMES.index(sine), FEATURE_NAMES.index(cosine))
                       for sine, cosine in (("sun_azimuth_sin", "sun_azimuth_cos"),
                                            ("day_of_year_sin", "day_of_year_cos")))


@dataclass(frozen=True)
class SupportPolicy:
    """Fixed experimental policy; its complete hash travels with every report."""

    version: str = "residual-training-support-v1"
    lower_quantile: float = 0.01
    upper_quantile: float = 0.99
    envelope_margin_fraction: float = 0.1
    joint_range_fraction: float = 0.25
    azimuth_tolerance_deg: float = 20.0
    season_tolerance_days: float = 60.0
    baseline_floor_fraction: float = 0.02
    max_prototypes: int = 4096

    def __post_init__(self):
        if self.version != "residual-training-support-v1":
            raise ValueError("unknown support policy")
        for name in ("lower_quantile", "upper_quantile", "envelope_margin_fraction", "joint_range_fraction",
                     "azimuth_tolerance_deg", "season_tolerance_days", "baseline_floor_fraction"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("nonfinite support policy")
        if (not 0 <= self.lower_quantile < self.upper_quantile <= 1
                or not 0 <= self.envelope_margin_fraction <= 1
                or not 0 < self.joint_range_fraction <= 1
                or not 0 < self.azimuth_tolerance_deg <= 180
                or not 0 < self.season_tolerance_days <= 182.62125
                or not 0 <= self.baseline_floor_fraction <= 1
                or type(self.max_prototypes) is not int or not 1 <= self.max_prototypes <= 4096):
            raise ValueError("invalid support policy")

    def as_dict(self):
        return {**asdict(self), "linear_floors": dict(LINEAR_FLOORS),
                "joint_metric": "nearest_max_linear_and_circular_distance",
                "prototype_selection": "unique_vectors_lexicographic_even_indices"}

    @property
    def sha256(self):
        return hashlib.sha256(json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class SupportAssessment:
    supported: bool | None
    reason: str
    outside_features: tuple[str, ...] = ()
    nearest_distance: float | None = None
    policy: str = "residual-training-support-v1"

    def as_dict(self):
        return {**asdict(self), "outside_features": list(self.outside_features)}


@dataclass
class _SupportCell:
    lower: np.ndarray
    upper: np.ndarray
    scales: np.ndarray
    prototypes: np.ndarray
    report: dict


def _weighted_quantile(values, weights, probability):
    order = np.argsort(values, kind="stable")
    cumulative = np.cumsum(weights[order])
    index = min(len(order) - 1, int(np.searchsorted(cumulative, probability * cumulative[-1])))
    return float(values[order[index]])


class SupportGuardLearner(ResidualLearner):
    """Explicit offline alternative; reference predictions remain accessible.

    ``status`` is the unchanged reference activation report. ``support_report``
    is a separate candidate report; it must not be called productive validation.
    Training support is rebuilt on every fit and is never borrowed from another
    output stage, regime or lead bin. Supported predictions are byte-for-byte
    equivalent dataclass values, including their existing empirical bounds.
    """

    def __init__(self, *, support_policy: SupportPolicy | None = None, **kwargs):
        super().__init__(**kwargs)
        self.support_policy = support_policy or SupportPolicy()
        self._support: dict[tuple[str, str, int], _SupportCell] = {}

    def fit(self, samples, as_of, *, output_caps=None, diagnostics=None):
        self._support.clear()
        return super().fit(samples, as_of, output_caps=output_caps, diagnostics=diagnostics)

    def _capture_training_support(self, inverter, regime, train):
        policy = self.support_policy
        for index, (_, lead_min, lead_max, _) in self._models[inverter, regime][1].items():
            rows = [row for row in train if lead_bin(row.features["lead_hours"]) == index
                    and lead_min <= row.features["lead_hours"] <= lead_max]
            if not rows:
                continue
            matrix = np.asarray([_vector(row.features) for row in rows], dtype=float)
            weights = _weights(rows)
            linear = matrix[:, LINEAR_INDICES]
            lower = np.array([_weighted_quantile(linear[:, pos], weights, policy.lower_quantile)
                              for pos in range(len(LINEAR_NAMES))])
            upper = np.array([_weighted_quantile(linear[:, pos], weights, policy.upper_quantile)
                              for pos in range(len(LINEAR_NAMES))])
            floors = np.array(list(LINEAR_FLOORS.values()))
            floors[0] = max(floors[0], policy.baseline_floor_fraction * upper[0])
            margin = np.maximum(floors, (upper - lower) * policy.envelope_margin_fraction)
            scales = np.maximum(floors, (upper - lower) * policy.joint_range_fraction)
            unique = np.unique(matrix, axis=0)
            prototypes = unique
            if len(unique) > policy.max_prototypes:
                indices = np.linspace(0, len(unique) - 1, policy.max_prototypes, dtype=int)
                prototypes = unique[indices]
            report = {
                "state": "ready", "training_rows": len(rows), "unique_feature_vectors": len(unique),
                "prototype_count": len(prototypes), "prototype_reduction": len(prototypes) != len(unique),
                "training_target_hours": _target_hours(rows),
                "training_target_days": len({row.start.astimezone(self.timezone).date() for row in rows}),
                "latest_training_observed_at": max(row.observed_at for row in rows).isoformat(),
                "training_target_start": min(row.start for row in rows).isoformat(),
                "training_target_end": max(row.end for row in rows).isoformat(),
                "envelope": {name: {"lower": float(lower[pos] - margin[pos]),
                                    "upper": float(upper[pos] + margin[pos]),
                                    "joint_scale": float(scales[pos])}
                             for pos, name in enumerate(LINEAR_NAMES)},
            }
            self._support[inverter, regime, index] = _SupportCell(lower - margin, upper + margin,
                                                                 scales, prototypes, report)

    def reference_predict(self, inverter_id, features, baseline_w, cap_w):
        return super().predict(inverter_id, features, baseline_w, cap_w)

    def _assess(self, inverter_id, features, reference):
        if not reference.status.startswith("residual"):
            return SupportAssessment(None, "reference_fallback")
        vector = np.asarray(_vector(features), dtype=float)
        key = (inverter_id, feature_regime(features), lead_bin(float(features["lead_hours"])))
        cell = self._support.get(key)
        if cell is None:
            return SupportAssessment(False, "missing_training_support")
        # The base learner accepts finite sin/cos inputs; the support candidate
        # additionally requires actual circular coordinates for its chord metric.
        if any(not math.isclose(math.hypot(vector[a], vector[b]), 1.0, abs_tol=1e-6)
               for a, b in CIRCULAR_PAIRS):
            return SupportAssessment(False, "invalid_circular_features")
        linear = vector[list(LINEAR_INDICES)]
        outside = tuple(name for pos, name in enumerate(LINEAR_NAMES)
                        if linear[pos] < cell.lower[pos] - 1e-9 or linear[pos] > cell.upper[pos] + 1e-9)
        if outside:
            return SupportAssessment(False, "marginal_range", outside)
        distances = np.max(np.abs(cell.prototypes[:, LINEAR_INDICES] - linear) / cell.scales, axis=1)
        for (a, b), chord in zip(CIRCULAR_PAIRS, (
                2 * math.sin(math.radians(self.support_policy.azimuth_tolerance_deg) / 2),
                2 * math.sin(math.pi * self.support_policy.season_tolerance_days / 365.2425)), strict=True):
            circular = np.hypot(cell.prototypes[:, a] - vector[a], cell.prototypes[:, b] - vector[b]) / chord
            distances = np.maximum(distances, circular)
        nearest = float(np.min(distances))
        return SupportAssessment(nearest <= 1 + 1e-9,
                                 "supported" if nearest <= 1 + 1e-9 else "joint_distance",
                                 nearest_distance=nearest)

    def assess(self, inverter_id, features, baseline_w, cap_w):
        return self._assess(inverter_id, features, self.reference_predict(inverter_id, features, baseline_w, cap_w))

    def predict(self, inverter_id, features, baseline_w, cap_w):
        reference = self.reference_predict(inverter_id, features, baseline_w, cap_w)
        assessment = self._assess(inverter_id, features, reference)
        if assessment.supported is False:
            return Prediction(min(baseline_w, cap_w), status=f"physics_support_{assessment.reason}")
        return reference

    def support_report(self):
        cells = {}
        for (inverter, regime, index), cell in sorted(self._support.items()):
            cells.setdefault(inverter, {}).setdefault(regime, {})[LEAD_BIN_NAMES[index]] = cell.report
        # Return detached JSON so a report consumer cannot mutate the candidate.
        return json.loads(json.dumps({"operational_use": False, "training_only": True,
                                      "policy": self.support_policy.as_dict(),
                                      "policy_sha256": self.support_policy.sha256, "cells": cells}))
