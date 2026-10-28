"""Complete-trajectory energy distributions and chronological offline scores.

These are raw ensemble probabilities until an explicit calibration is applied.
No weather-member identity is joined across different products or model runs.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import hashlib
import math

from .archive import canonical_bytes
from .models import ForecastResult, finite_number, utc_time


@dataclass(frozen=True)
class EnergyDistribution:
    family: str
    product: str
    start: datetime
    end: datetime
    values_kwh: tuple[float, ...]
    weights: tuple[float, ...]
    member_ids: tuple[str, ...]
    expected_members: int
    excluded_members: tuple[str, ...] = ()
    status: str = "raw_ensemble_uncalibrated"
    calibration_sha256: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "start", utc_time(self.start))
        object.__setattr__(self, "end", utc_time(self.end))
        if self.end <= self.start:
            raise ValueError("invalid distribution window")
        if not self.values_kwh or len(self.values_kwh) != len(self.weights) or len(self.member_ids) != len(self.weights):
            raise ValueError("invalid distribution cohort")
        if len(set(self.member_ids)) != len(self.member_ids):
            raise ValueError("duplicate distribution members")
        if (isinstance(self.expected_members, bool) or not isinstance(self.expected_members, int)
                or self.expected_members < len(self.member_ids)):
            raise ValueError("invalid expected distribution members")
        for value in self.values_kwh:
            finite_number(value, "energy", 0)
        for weight in self.weights:
            finite_number(weight, "weight", 0)
        if not math.isclose(sum(self.weights), 1, abs_tol=1e-12):
            raise ValueError("distribution weights must sum to one")

    def quantile(self, probability: float) -> float:
        probability = finite_number(probability, "quantile", 0, 1)
        cumulative = 0.0
        for value, weight in sorted(zip(self.values_kwh, self.weights, strict=True)):
            cumulative += weight
            if cumulative + 1e-14 >= probability:
                return value
        return max(self.values_kwh)

    def probability_below(self, threshold_kwh: float) -> float:
        threshold_kwh = finite_number(threshold_kwh, "threshold", 0)
        return sum(weight for value, weight in zip(self.values_kwh, self.weights, strict=True) if value < threshold_kwh)

    def summary(self, thresholds=()) -> dict:
        return {"q10_kwh": self.quantile(.1), "q50_kwh": self.quantile(.5), "q90_kwh": self.quantile(.9),
                "threshold_probability_below": {str(t): self.probability_below(t) for t in thresholds},
                "status": self.status, "member_count": len(self.member_ids), "expected_members": self.expected_members,
                "excluded_members": list(self.excluded_members), "calibration_sha256": self.calibration_sha256}


def window_distribution(product: str, family: str, results: dict[str, ForecastResult],
                        start: datetime, end: datetime, expected_members: int,
                        stage_ids: tuple[str, ...], *, quorum: float = 1.0) -> EnergyDistribution:
    """Sum synchronous stages within each member before deriving quantiles.

    Default quorum requires every expected member. A lower explicitly selected
    quorum reports its incomplete cohort; an absent member is never zero energy.
    """
    quorum = finite_number(quorum, "quorum", 0, 1)
    if quorum <= 0 or isinstance(expected_members, bool) or not isinstance(expected_members, int) or expected_members < 1:
        raise ValueError("invalid member quorum/count")
    if not stage_ids or len(set(stage_ids)) != len(stage_ids) or len(results) > expected_members:
        raise ValueError("invalid expected stages/members")
    start, end = utc_time(start), utc_time(end)
    values, ids, excluded = [], [], []
    for member_id, result in sorted(results.items()):
        stages = [result.energy_kwh(start, end, stage) for stage in stage_ids]
        if any(value is None for value in stages):
            excluded.append(member_id)
        else:
            values.append(sum(stages))
            ids.append(member_id)
    if len(ids) < math.ceil(expected_members * quorum) or not ids:
        raise ValueError("insufficient complete same-window member cohort")
    status = "raw_ensemble_uncalibrated" if len(ids) == expected_members else "raw_ensemble_uncalibrated_incomplete_cohort"
    return EnergyDistribution(family, product, start, end, tuple(values), (1 / len(ids),) * len(ids), tuple(ids),
                              expected_members, tuple(excluded), status)


def combine_families(distributions: tuple[EnergyDistribution, ...], family_weights: dict[str, float] | None = None):
    """Mix family distributions with family weights independent of member count.

    Choose IFS Europe OR IFS025 before calling: two products of the same family
    do not constitute two independent families. Different windows never mix.
    """
    if not distributions or len({d.family for d in distributions}) != len(distributions):
        raise ValueError("choose exactly one product per family")
    if len({(d.start, d.end) for d in distributions}) != 1:
        raise ValueError("family windows differ")
    family_weights = family_weights or {d.family: 1 for d in distributions}
    if set(family_weights) != {d.family for d in distributions}:
        raise ValueError("explicit weight required for every family")
    for weight in family_weights.values():
        finite_number(weight, "family weight", 0)
    total = sum(family_weights.values())
    if total <= 0:
        raise ValueError("zero family weight")
    values, weights, ids = [], [], []
    for distribution in distributions:
        values.extend(distribution.values_kwh)
        weights.extend(w * family_weights[distribution.family] / total for w in distribution.weights)
        ids.extend(f"{distribution.product}:{member}" for member in distribution.member_ids)
    first = distributions[0]
    return EnergyDistribution("mixture", "+".join(d.product for d in distributions), first.start, first.end,
                              tuple(values), tuple(weights), tuple(ids), sum(d.expected_members for d in distributions),
                              status="raw_family_mixture_uncalibrated")


@dataclass(frozen=True)
class CalibrationCase:
    """A qualified measurement and the raw forecast frozen before its target."""
    issued_at: datetime
    target_start: datetime
    target_end: datetime
    available_at: datetime
    predicted_median_kwh: float
    actual_kwh: float
    family: str
    product: str
    qualified: bool = True


def calibrate_bias(distribution: EnergyDistribution, cases: tuple[CalibrationCase, ...],
                   cutoff: datetime, *, min_samples: int = 20) -> EnergyDistribution:
    """Chronological median-bias correction; does not certify spread reliability.

    The caller must provide the same declared family/window/lead stratum. This
    method only corrects location and intentionally retains explicit method text.
    """
    cutoff = utc_time(cutoff)
    if cutoff > distribution.start:
        raise ValueError("calibration cutoff follows target start")
    if not distribution.status.startswith("raw_"):
        raise ValueError("calibration requires a raw distribution")
    if isinstance(min_samples, bool) or not isinstance(min_samples, int) or min_samples < 1:
        raise ValueError("invalid minimum calibration sample count")
    def lead_bin(issue, start, end):
        hours = ((start + (end - start) / 2) - issue).total_seconds() / 3600
        return next((index for index, edge in enumerate((6, 24, 48, 96)) if hours < edge), 4)

    eligible, identities = [], set()
    for case in cases:
        issue, start, end, available = (utc_time(t) for t in (
            case.issued_at, case.target_start, case.target_end, case.available_at))
        actual = finite_number(case.actual_kwh, "actual", 0)
        median = finite_number(case.predicted_median_kwh, "median", 0)
        if (case.qualified is not True or issue > start or end <= start or end > available
                or available > cutoff or end >= cutoff or case.family != distribution.family
                or case.product != distribution.product or end - start != distribution.end - distribution.start
                or lead_bin(issue, start, end) != lead_bin(cutoff, distribution.start, distribution.end)):
            continue
        identity = (start.isoformat(), end.isoformat())
        if identity in identities:
            raise ValueError("duplicate calibration case")
        identities.add(identity)
        eligible.append({"issued_at": issue.isoformat(), "target_start": start.isoformat(), "target_end": end.isoformat(),
                         "available_at": available.isoformat(), "actual_kwh": actual, "median_kwh": median})
    eligible.sort(key=lambda row: (row["target_end"], row["issued_at"]))
    if len(eligible) < min_samples:
        raise ValueError("insufficient prior qualified calibration cases")
    from statistics import median
    bias = median(row["actual_kwh"] - row["median_kwh"] for row in eligible)
    fingerprint = hashlib.sha256(canonical_bytes({"method": "median-bias-v1", "cutoff": cutoff.isoformat(),
                                                  "family": distribution.family, "product": distribution.product,
                                                  "window_seconds": (distribution.end - distribution.start).total_seconds(),
                                                  "cases": eligible})).hexdigest()
    return replace(distribution, values_kwh=tuple(max(0, v + bias) for v in distribution.values_kwh),
                   status="empirical_median_bias_corrected_spread_unvalidated", calibration_sha256=fingerprint)


def probability_scores(distribution: EnergyDistribution, actual_kwh: float, thresholds=()) -> dict:
    """Weighted empirical CRPS, pinball loss, Brier and central-80% coverage."""
    actual_kwh = finite_number(actual_kwh, "actual", 0)
    values, weights = distribution.values_kwh, distribution.weights
    crps = sum(w * abs(v - actual_kwh) for v, w in zip(values, weights, strict=True))
    crps -= .5 * sum(w * z * abs(v - u) for v, w in zip(values, weights, strict=True)
                    for u, z in zip(values, weights, strict=True))
    losses = {}
    for quantile in (.1, .5, .9):
        error = actual_kwh - distribution.quantile(quantile)
        losses[str(quantile)] = max(quantile * error, (quantile - 1) * error)
    return {"crps_kwh": max(0, crps), "quantile_loss_kwh": losses,
            "coverage_80": distribution.quantile(.1) <= actual_kwh <= distribution.quantile(.9),
            "width_80_kwh": distribution.quantile(.9) - distribution.quantile(.1),
            "brier": {str(t): (distribution.probability_below(t) - (actual_kwh < t)) ** 2 for t in thresholds}}
