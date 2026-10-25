"""Conditional paired target-day bootstrap for a declared forecast test family.

``paired_day_bootstrap(evaluate_forecasts(...))`` returns a JSON-safe result.
Every expected inverter/horizon and both references belong to the family, even
when data are absent. Only target days containing *all* declared issues in *all*
strata enter the joint comparison. Multiple issues are first averaged within
their target-day/stratum. The same sampled target-day indices are used for every
inverter, horizon and reference, preserving their within-day dependence.

Statistics are day-weighted mean absolute energy errors, their paired difference
(candidate minus reference, kWh), and skill 1 - MAE(candidate)/MAE(reference).
Percentile intervals use nominal family confidence 95%, with Bonferroni over
the predeclared stratum x reference x two-statistic family. This is an approximate
bootstrap statement conditional on representative, exchangeable target-day
blocks; weather persistence across days, selection, regime drift and season
coverage can invalidate that assumption. It is no exact coverage guarantee,
provenance certification, seasonal generalization or production authorization.

Acceptance requires the separate descriptive gate, both named references and
every declared stratum: the skill interval's lower bound reaches the predeclared
improvement threshold, the difference interval is strictly negative, and the
point absolute energy bias does not increase. No post-outcome threshold choice
or aggregate substitution is performed. Resamples are raised, solely from the
declared family size, to at least 20 expected draws in each endpoint tail. This
reduces Monte Carlo granularity; it does not fix bootstrap coverage limitations.

Primary methodological references (accessed 2026-10-24):
https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html
  Paired samples use shared resampled indices; percentile and seeded sampling.
https://itl.nist.gov/div898/handbook/prc/section4/prc473.htm
  Bonferroni intervals for a finite, preselected comparison family.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
import math
from typing import Mapping

import numpy as np

REFERENCES = ("helios", "open_meteo")


def _nonnegative(value) -> bool:
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and 0 <= value <= 1e12)


def _key(cutoff: str, target_day: str) -> tuple[str, str]:
    parsed = datetime.fromisoformat(cutoff)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Bootstrap cutoffs must be timezone-aware")
    day = date.fromisoformat(target_day).isoformat()
    return parsed.astimezone(timezone.utc).isoformat(), day


def paired_day_bootstrap(
    report: Mapping,
    *,
    candidate: str = "adaptive",
    references: tuple[str, ...] = REFERENCES,
    confidence_level: float = 0.95,
    n_resamples: int = 20000,
    seed: int = 20261024,
    min_paired_days: int = 30,
) -> dict:
    """Evaluate the existing report's declared family without mutating it.

    The declared family comes from ``strata[*].expected_pairs`` emitted from
    the expected evaluation schedule, never from successful energy rows alone.
    Missing/ambiguous pairs remove their whole target day from the common set.
    At least max(30, min_paired_days, report.policy.min_paired_days) common days
    are required. Invalid policy/schedule raises ValueError; missing evidence
    returns an explicit failed gate. Undefined reference MAE/skill stays null.
    """
    references = tuple(references)
    if (candidate != "adaptive"
            or set(references) != set(REFERENCES) or len(references) != 2
            or candidate in references or not 0.95 <= confidence_level < 1
            or isinstance(n_resamples, bool) or not isinstance(n_resamples, int) or n_resamples < 1000
            or isinstance(seed, bool) or not isinstance(seed, int) or seed < 0
            or isinstance(min_paired_days, bool) or not isinstance(min_paired_days, int) or min_paired_days < 30):
        raise ValueError("Invalid predeclared bootstrap policy")
    policy = report.get("policy", {})
    declared_minimum = policy.get("min_paired_days", 30)
    threshold = policy.get("min_relative_improvement", 0.05)
    if (isinstance(declared_minimum, bool) or not isinstance(declared_minimum, int) or declared_minimum < 1
            or isinstance(threshold, bool) or not isinstance(threshold, (int, float))
            or not math.isfinite(threshold) or not 0.05 <= threshold < 1):
        raise ValueError("Report policy cannot weaken the bootstrap acceptance threshold")
    minimum = max(30, min_paired_days, declared_minimum)
    strata = report.get("strata", {})
    if not isinstance(strata, Mapping):
        raise ValueError("Expected strata must be a mapping")
    family_size = len(strata) * len(references) * 2
    tail_probability = (1 - confidence_level) / (2 * family_size) if family_size else None
    resamples = max(n_resamples, math.ceil(20 / tail_probability)) if tail_probability else n_resamples
    if resamples > 2_000_000 or resamples * max(1, len(strata)) * len(references) > 20_000_000:
        raise ValueError("Declared bootstrap family/confidence exceeds the bounded offline computation budget")
    result = {
        "policy_version": 1, "policy_id": "paired-target-day-bootstrap-v1",
        "random_generator": "PCG64", "quantile_method": "linear",
        "state": "insufficient_evidence", "accepted": False,
        "method": "paired_target_day_percentile_bootstrap_bonferroni",
        "interpretation": "conditional_on_exchangeable_representative_target_days",
        "assumptions": ["target_day_blocks_are_exchangeable_and_representative",
                        "within_day_dependence_preserved", "cross_day_persistence_not_modelled",
                        "schedule_thresholds_and_test_family_predeclared",
                        "archive_provenance_verified_separately"],
        "candidate": candidate, "references": list(references),
        "family_confidence_level": confidence_level, "family_size": family_size,
        "individual_interval_confidence_level": 1 - (1 - confidence_level) / family_size if family_size else None,
        "endpoint_tail_probability": tail_probability,
        "seed": seed, "requested_resamples": n_resamples, "resamples": resamples,
        "min_paired_days": minimum, "min_relative_improvement": threshold,
        "joint_target_days": [], "joint_target_day_count": 0,
        "strata": {}, "gate_reasons": [],
        "descriptive_gate_passed": bool(report.get("comparison_eligible") is True
                                          and report.get("supports_improvement_over_both_references_on_paired_archive") is True),
    }
    reasons = result["gate_reasons"]
    if any(source not in report.get("sources", []) for source in (candidate, *references)):
        reasons.append("missing_declared_candidate_or_reference")
    if not strata:
        reasons.append("missing_declared_strata")
        return result
    expected: dict[str, set[tuple[str, str]]] = {}
    scope_lookup: dict[tuple[str, str], str] = {}
    for name, stratum in sorted(strata.items()):
        if (not isinstance(name, str) or not isinstance(stratum, Mapping)
                or not isinstance(stratum.get("inverter_id"), str) or not stratum["inverter_id"]
                or not isinstance(stratum.get("horizon"), str) or not stratum["horizon"]):
            raise ValueError("Invalid declared stratum")
        scope = stratum["inverter_id"], stratum["horizon"]
        if scope in scope_lookup:
            raise ValueError("Ambiguous declared strata")
        scope_lookup[scope] = name
        planned = stratum.get("expected_pairs")
        if not isinstance(planned, list) or not planned:
            reasons.append(f"missing_expected_schedule:{name}")
            expected[name] = set()
        else:
            expected[name] = {_key(row["cutoff"], row["target_day"]) for row in planned}
    rows: dict[str, dict[tuple, list[Mapping]]] = defaultdict(lambda: defaultdict(list))
    for row in report.get("energy_pairs", []):
        scope = row.get("inverter_id"), row.get("horizon")
        name = scope_lookup.get(scope)
        if name is None:
            reasons.append("unexpected_energy_stratum")
            continue
        key = _key(row["cutoff"], row["target_day"])
        if key not in expected[name]:
            reasons.append(f"unexpected_energy_pair:{name}")
            continue
        rows[name][key].append(row)
    # Day values store absolute errors and signed errors for candidate + refs.
    sources = (candidate, *references)
    day_values = {}
    complete_days = {}
    for name in sorted(strata):
        planned_by_day: dict[str, list[tuple]] = defaultdict(list)
        for key in expected[name]:
            planned_by_day[key[1]].append(key)
        values_by_day = {}
        for day, day_keys in sorted(planned_by_day.items()):
            day_errors = []
            for key in sorted(day_keys):
                duplicates = rows[name].get(key, [])
                fingerprints = []
                for row in duplicates:
                    forecasts = row.get("forecasts_kwh", {})
                    actual = row.get("actual_kwh")
                    if (not _nonnegative(actual) or not isinstance(forecasts, Mapping)
                            or any(not _nonnegative(forecasts.get(source)) for source in sources)):
                        fingerprints.append(None)
                    else:
                        fingerprints.append((actual, *(forecasts[source] for source in sources)))
                if not fingerprints or None in fingerprints or len(set(fingerprints)) != 1:
                    break
                actual, *predictions = fingerprints[0]
                day_errors.append([prediction - actual for prediction in predictions])
            else:
                signed = np.asarray(day_errors, dtype=float)
                values_by_day[day] = (np.abs(signed).mean(axis=0), signed.mean(axis=0))
        day_values[name] = values_by_day
        complete_days[name] = set(values_by_day)
        result["strata"][name] = {
            "inverter_id": strata[name]["inverter_id"], "horizon": strata[name]["horizon"],
            "expected_target_days": len(planned_by_day), "complete_target_days": len(values_by_day),
            "missing_or_invalid_target_days": sorted(set(planned_by_day) - set(values_by_day)),
            "comparisons": {reference: {"accepted": False, "candidate_mae_kwh": None,
                                        "reference_mae_kwh": None, "mae_difference_kwh": None,
                                        "relative_skill": None, "mae_difference_ci_kwh": None,
                                        "relative_skill_ci": None} for reference in references},
        }
        if len(values_by_day) < minimum:
            reasons.append(f"insufficient_paired_target_days:{name}")
    joint_days = sorted(set.intersection(*complete_days.values()))
    result["joint_target_days"], result["joint_target_day_count"] = joint_days, len(joint_days)
    if len(joint_days) < minimum:
        reasons.append("insufficient_joint_target_days")
    if reasons:
        result["gate_reasons"] = sorted(set(reasons))
        return result
    names = sorted(strata)
    errors = np.asarray([[day_values[name][day][0] for name in names] for day in joint_days])
    signed_errors = np.asarray([[day_values[name][day][1] for name in names] for day in joint_days])
    means, biases = errors.mean(axis=0), signed_errors.mean(axis=0)
    bootstrap_difference = np.empty((resamples, len(names), len(references)))
    bootstrap_skill = np.empty_like(bootstrap_difference)
    rng = np.random.Generator(np.random.PCG64(seed))
    for start in range(0, resamples, 512):
        stop = min(resamples, start + 512)
        indices = rng.integers(0, len(joint_days), size=(stop - start, len(joint_days)))
        boot_means = errors[indices].mean(axis=1)
        reference_means = boot_means[:, :, 1:]
        bootstrap_difference[start:stop] = boot_means[:, :, :1] - reference_means
        ratios = np.full_like(reference_means, np.nan)
        np.divide(boot_means[:, :, :1], reference_means, out=ratios, where=reference_means > 0)
        bootstrap_skill[start:stop] = 1 - ratios
    for stratum_index, name in enumerate(names):
        for reference_index, reference in enumerate(references):
            candidate_mae, reference_mae = float(means[stratum_index, 0]), float(means[stratum_index, reference_index + 1])
            difference = candidate_mae - reference_mae
            skill = 1 - candidate_mae / reference_mae if reference_mae > 0 else None
            delta_samples = bootstrap_difference[:, stratum_index, reference_index]
            skill_samples = bootstrap_skill[:, stratum_index, reference_index]
            delta_ci = [float(value) for value in np.quantile(
                delta_samples, [tail_probability, 1 - tail_probability], method="linear")]
            undefined = int(np.count_nonzero(~np.isfinite(skill_samples)))
            skill_ci = None if undefined else [float(value) for value in np.quantile(
                skill_samples, [tail_probability, 1 - tail_probability], method="linear")]
            bias_ok = abs(biases[stratum_index, 0]) <= abs(biases[stratum_index, reference_index + 1]) + 1e-12
            supported = bool(skill_ci is not None and skill is not None and skill >= threshold
                             and skill_ci[0] >= threshold and delta_ci[1] < 0 and bias_ok)
            result["strata"][name]["comparisons"][reference] = {
                "accepted": supported, "paired_target_days": len(joint_days),
                "candidate_mae_kwh": candidate_mae, "reference_mae_kwh": reference_mae,
                "mae_difference_kwh": difference, "relative_skill": skill,
                "mae_difference_ci_kwh": delta_ci, "relative_skill_ci": skill_ci,
                "candidate_bias_kwh": float(biases[stratum_index, 0]),
                "reference_bias_kwh": float(biases[stratum_index, reference_index + 1]),
                "absolute_bias_not_increased": bool(bias_ok),
                "undefined_skill_resamples": undefined,
            }
            if not supported:
                reasons.append(f"unsupported_stratum_reference:{name}:{reference}")
    if not result["descriptive_gate_passed"]:
        reasons.append("descriptive_gate_not_passed")
    result["accepted"] = not reasons
    result["state"] = "accepted_conditional" if result["accepted"] else "not_supported"
    result["gate_reasons"] = sorted(set(reasons))
    return result
