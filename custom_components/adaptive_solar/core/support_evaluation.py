"""Descriptive offline comparison of the residual stage on frozen inputs.

This does not replay the final HA forecast: downstream power nowcast and its
reference selection are outside this experiment. Caller-qualified measurements
are evidence assertions, not source qualification performed by this module.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from bisect import bisect_right
from datetime import datetime
import hashlib
import math
from zoneinfo import ZoneInfo

from .archive import canonical_bytes, validate_envelope
from .evaluation import ActualRecord, EvaluationWindow, ForecastAttempt, ForecastRecord, _interval_mean, evaluate_forecasts
from .learning import LEAD_BIN_NAMES, feature_regime, lead_bin
from .learning_support import SupportGuardLearner
from .models import ForecastPoint, SiteConfig, TrainingSample, finite_number, midpoint_lead_hours
from .replay import hydrate_forecast, reconstruct_state, timestamp, timed_record, verify_weather_receipts

SCHEMA = "adaptive-solar-support-evaluation-v1"
ARMS = ("physics", "residual", "guarded_residual")
MAX_TASKS = 100_000
MAX_FITS = 256


def _digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _list(value, name, maximum):
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f"invalid or oversized {name}")
    return value


def _identifier(value):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError("identifier must be a nonempty string")
    return value


def _json_safe(value):
    """Native rejected-fit reports may contain infinity; JSON uses null."""
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value.isoformat() if isinstance(value, datetime) else value


def _qualified_actuals(rows):
    actuals, counts = [], Counter()
    seen = set()
    for raw in _list(rows, "actuals", MAX_TASKS):
        if not isinstance(raw, dict):
            raise ValueError("actual must be an object")
        identity = canonical_bytes(raw)
        if identity in seen:
            continue
        seen.add(identity)
        value = dict(raw)
        qualified = value.pop("qualified", False)
        quality_source = value.pop("quality_source", None)
        if type(qualified) is not bool:
            raise ValueError("actual qualification must be boolean")
        if qualified and (not isinstance(quality_source, str) or not quality_source.strip()):
            raise ValueError("qualified actual needs quality_source")
        actual = ActualRecord.from_dict(value)
        if qualified:
            finite_number(actual.power_w, "qualified actual power", 0)
            if actual.observed_at < actual.end:
                raise ValueError("actual availability precedes interval end")
            counts["qualified"] += 1
        else:
            # Preserve invalid support so it cannot be hidden by a competing
            # positive record of the same target or interpreted as zero.
            actual = ActualRecord(actual.start, actual.end, actual.inverter_id,
                                  None, actual.observed_at, actual.curtailed)
            counts["unqualified"] += 1
        actuals.append(actual)
    return actuals, dict(counts)


def _fit_models(payload, timezone_name, as_of):
    fits, models, reports = {}, {}, {}
    for raw in _list(payload["fits"], "fits", MAX_FITS):
        if not isinstance(raw, dict):
            raise ValueError("fit must be an object")
        identifier = _identifier(raw["id"])
        if identifier in fits:
            if canonical_bytes(fits[identifier]) != canonical_bytes(raw):
                raise ValueError("conflicting fit identity")
            continue
        available = raw.get("learner_available", True)
        if type(available) is not bool:
            raise ValueError("learner_available must be boolean")
        caps = raw["output_caps_w"]
        if not isinstance(caps, dict) or not caps:
            raise ValueError("fit requires output caps")
        for key, cap in caps.items():
            _identifier(key)
            if finite_number(cap, "output cap", 0) <= 0:
                raise ValueError("output cap must be positive")
        rows = _list(raw["fit_samples"], "fit_samples", 100_000)
        samples = tuple(timed_record(TrainingSample, row, {"issued_at", "start", "end", "observed_at"})
                        for row in rows)
        cutoff = timestamp(raw["fit_as_of"]) if raw.get("fit_as_of") is not None else None
        if (available and cutoff is None) or (not available and (cutoff is not None or samples)):
            raise ValueError("fit cutoff/samples disagree with learner availability")
        if cutoff is not None and (cutoff > as_of or any(row.observed_at > cutoff for row in samples)):
            raise ValueError("fitted label or fit cutoff is in the future")
        learner = SupportGuardLearner(timezone_name=timezone_name, output_caps=caps)
        details = {}
        if available:
            learner.fit(samples, cutoff, diagnostics=details)
        support = learner.support_report()
        cells = [cell for stage in learner.status.values() for regime in stage.get("regimes", {}).values()
                 for cell in regime.get("lead_bins", {}).values()]
        counts = {"named_possible": len(caps) * 2 * len(LEAD_BIN_NAMES),
                  "validation_evaluated": sum("physics_validation_mae_w" in cell for cell in cells),
                  "active": sum(cell.get("state") == "active" for cell in cells),
                  "guard_ready": sum(len(bins) for stage in support["cells"].values() for bins in stage.values()),
                  "scope": "one_fitted_snapshot_potential_cells_not_independent_tests"}
        models[identifier] = learner
        fits[identifier] = raw
        reports[identifier] = {"fit_as_of": raw.get("fit_as_of"), "input_sha256": _digest(raw),
                               "learner_available": available, "learner_status": _json_safe(learner.status),
                               "rejections": details, "support": support, "cell_counts": counts}
    return fits, models, reports


def _unique_tasks(rows):
    unique = {}
    for raw in _list(rows, "tasks", MAX_TASKS):
        if not isinstance(raw, dict):
            raise ValueError("task must be an object")
        raw = dict(raw)
        for name in ("issued_at", "start", "end", "available_at"):
            if name in raw:
                raw[name] = timestamp(raw[name]).isoformat()
        raw.setdefault("available_at", raw["issued_at"])
        key = tuple(raw[name] for name in ("issued_at", "available_at", "inverter_id", "start", "end"))
        if key in unique and canonical_bytes(unique[key]) != canonical_bytes(raw):
            raise ValueError("conflicting forecast task")
        unique[key] = raw
    return list(unique.values())


def _attempts(payload, rows, fits, as_of):
    """Keep empty attempts without inventing target intervals or feature vectors."""
    unique = {}
    stages = {stage for fit in fits.values() for stage in fit["output_caps_w"]}
    implicit = [_json_safe({key: row[key] for key in ("issued_at", "available_at", "inverter_id")}) for row in rows]
    for raw in [*_list(payload.get("attempts", []), "attempts", MAX_TASKS), *implicit]:
        if not isinstance(raw, dict) or set(raw) != {"issued_at", "available_at", "inverter_id"}:
            raise ValueError("invalid forecast attempt")
        issue, available = timestamp(raw["issued_at"]), timestamp(raw["available_at"])
        stage = _identifier(raw["inverter_id"])
        if stage not in stages or not issue <= available <= as_of:
            raise ValueError("forecast attempt scope or chronology is invalid")
        key = stage, available
        if key in unique and unique[key]["issued_at"] != issue:
            raise ValueError("ambiguous forecast attempt at one availability timestamp")
        unique[key] = {"inverter_id": stage, "issued_at": issue, "available_at": available}
    return list(unique.values())


def _coverage(rows, actuals, as_of):
    """Compare only complete uncurtailed measurements, never clip actual means."""
    output = {}
    for arm in ("residual", "guarded_residual"):
        count = covered = 0
        hours = covered_hours = width_hours = 0.0
        for row in rows:
            prediction = row["predictions"][arm]
            if prediction["lower_w"] is None:
                continue
            candidates = [a for a in actuals if a.inverter_id == row["inverter_id"]
                          and a.start < row["end"] and a.end > row["start"]
                          and a.end <= a.observed_at <= as_of]
            if any(a.curtailed for a in candidates):
                continue
            actual = _interval_mean(candidates, row["start"], row["end"], clip=False)
            if actual is None:
                continue
            duration = (row["end"] - row["start"]).total_seconds() / 3600
            inside = prediction["lower_w"] <= actual <= prediction["upper_w"]
            count += 1
            covered += inside
            hours += duration
            covered_hours += duration * inside
            width_hours += duration * (prediction["upper_w"] - prediction["lower_w"])
        output[arm] = {"paired_bounded_tasks": count, "covered_tasks": covered,
                       "task_duration_hours": hours,
                       "duration_weighted_coverage": covered_hours / hours if hours else None,
                       "mean_width_w": width_hours / hours if hours else None,
                       "future_coverage_guaranteed": False}
    return output


def _daily_wins(evaluation):
    """One vote per complete target day/stratum, averaging its declared origins."""
    grouped = defaultdict(list)
    for row in evaluation["energy_pairs"]:
        key = row["inverter_id"] + "|" + row["horizon"]
        grouped[key, row["target_day"]].append(row)
    results = {}
    for key, stratum in evaluation["strata"].items():
        expected = Counter(row["target_day"] for row in stratum["expected_pairs"])
        pairs = {day: grouped[key, day] for day, count in expected.items() if len(grouped[key, day]) == count}
        comparisons = {}
        for left, right in (("residual", "physics"), ("guarded_residual", "residual"),
                            ("guarded_residual", "physics")):
            wins = 0
            for rows in pairs.values():
                errors = {arm: sum(abs(r["forecasts_kwh"][arm] - r["actual_kwh"]) for r in rows) / len(rows)
                          for arm in (left, right)}
                wins += errors[left] < errors[right]
            comparisons[left + "_vs_" + right] = {"winning_days": wins, "complete_days": len(pairs),
                                                     "fraction": wins / len(pairs) if pairs else None}
        results[key] = comparisons
    return results


def _scheduled_strata(rows, forecasts, windows, actuals, as_of, timezone_name, attempts, forecast_attempts):
    """Use the exact same newest available issue and tasks as overall scoring.

    A missing task has an unknown regime; it remains visible rather than being
    guessed into NWP. Windows may select older origins but must retain complete
    native target intervals: splitting/combining feature vectors has no contract.
    """
    indexed = defaultdict(dict)
    for row in rows:
        if row["available_at"] > row["start"]:
            continue
        key = row["start"], row["end"]
        bucket = indexed[row["inverter_id"], row["available_at"]]
        if key in bucket:
            raise ValueError("ambiguous residual task at one availability timestamp")
        bucket[key] = row
    for attempt in attempts:
        indexed[attempt["inverter_id"], attempt["available_at"]]
    issues = defaultdict(list)
    for stage, available in indexed:
        issues[stage].append(available)
    for values in issues.values():
        values.sort()
    grouped, selected = defaultdict(list), defaultdict(list)
    for window in sorted(set(windows), key=lambda w: (w.cutoff, w.inverter_id, w.start, w.end)):
        values = issues[window.inverter_id]
        position = bisect_right(values, min(window.cutoff, window.start, as_of)) - 1
        bucket = indexed.get((window.inverter_id, values[position]), {}) if position >= 0 else {}
        row = bucket.get((window.start, window.end))
        if row is None and any(r["start"] < window.end and r["end"] > window.start for r in bucket.values()):
            raise ValueError("schedule must preserve complete exported target intervals")
        key = (window.inverter_id, row["regime"] if row is not None else "unknown",
               LEAD_BIN_NAMES[lead_bin(midpoint_lead_hours(window.cutoff, window.start, window.end))])
        grouped[key].append(window)
        if row is not None:
            selected[key].append(row)
    result = {}
    for key, own_windows in sorted(grouped.items()):
        own = selected[key]
        score = evaluate_forecasts(forecasts, actuals, own_windows, as_of=as_of, sources=ARMS,
                                   forecast_attempts=forecast_attempts,
                                   timezone_name=timezone_name)
        result["|".join(key)] = {"inverter_id": key[0], "regime": key[1], "lead_bin": key[2],
                                "scheduled_tasks": len(own_windows), "available_tasks": len(own),
                                "paired_tasks": score["paired_intervals"],
                                "support_reasons": dict(Counter(r["support"]["reason"] for r in own)),
                                "guard_fallback_tasks": sum(r["support"]["supported"] is False for r in own),
                                "scores": {arm: score["scores"][arm]["overall"] for arm in ARMS},
                                "calibration": _coverage(own, actuals, as_of)}
    return result


def evaluate_support(payload):
    """Return a reproducible diagnostic report, never an activation decision."""
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise ValueError("unknown support evaluation schema")
    canonical_bytes(payload)  # Reject NaN and non-JSON input before fitting.
    timezone_name = payload["timezone"]
    ZoneInfo(timezone_name)
    as_of = timestamp(payload["as_of"])
    fits, models, fit_reports = _fit_models(payload, timezone_name, as_of)
    actuals, actual_counts = _qualified_actuals(payload.get("actuals", []))
    rows, forecasts, windows, ignored = [], [], [], Counter()
    for task in _unique_tasks(payload["tasks"]):
        identifier = _identifier(task["fit_id"])
        if identifier not in fits:
            raise ValueError("task refers to unknown fit")
        fit, learner = fits[identifier], models[identifier]
        issue = timestamp(task["issued_at"])
        available = timestamp(task.get("available_at", task["issued_at"]))
        start, end = timestamp(task["start"]), timestamp(task["end"])
        stage = _identifier(task["inverter_id"])
        if not issue <= available <= as_of or not issue <= start < end:
            raise ValueError("task timestamps are not prospective or available")
        if fit.get("fit_as_of") is not None and timestamp(fit["fit_as_of"]) > issue:
            raise ValueError("task predates fitted-state cutoff")
        if stage not in fit["output_caps_w"]:
            raise ValueError("task lacks declared output cap")
        baseline = finite_number(task["baseline_w"], "baseline_w", 0)
        features = task["features"]
        point = ForecastPoint(start, end, stage, baseline, baseline, features=features)
        lead = midpoint_lead_hours(issue, start, end)
        if not math.isclose(features.get("lead_hours", -1), lead, abs_tol=1e-12, rel_tol=1e-12):
            raise ValueError("task lead does not match original issue and target")
        cap = fit["output_caps_w"][stage]
        original = learner.reference_predict(stage, point.features, baseline, cap)
        candidate = learner.predict(stage, point.features, baseline, cap)
        assessment = learner.assess(stage, point.features, baseline, cap).as_dict()
        regime = feature_regime(point.features) or "invalid"
        predictions = {"physics": {"power_w": min(cap, baseline), "lower_w": None,
                                    "upper_w": None, "status": "physics"}}
        for arm, prediction in (("residual", original), ("guarded_residual", candidate)):
            predictions[arm] = {"power_w": prediction.power_w, "lower_w": prediction.lower_w,
                                "upper_w": prediction.upper_w, "status": prediction.status}
            if regime == "ghi":
                # The production engine withholds these unqualified live-GHI bounds.
                predictions[arm].update(lower_w=None, upper_w=None)
                if prediction.status == "residual_empirical_calibration":
                    predictions[arm]["status"] = "residual_no_uncertainty"
        row = {"fit_id": identifier, "issued_at": issue, "available_at": available,
               "start": start, "end": end, "inverter_id": stage, "regime": regime,
               "lead_bin": LEAD_BIN_NAMES[lead_bin(lead)], "support": assessment,
               "predictions": predictions}
        rows.append(row)
        if available > start:
            ignored["not_prospective_at_receipt"] += 1
            continue
        window = EvaluationWindow(available, start, end, stage,
                                  daylight=point.features.get("sun_elevation_deg", 0) > 0)
        windows.append(window)
        forecasts.extend(ForecastRecord(arm, available, start, end, stage, value["power_w"])
                         for arm, value in predictions.items())
    declared = payload.get("schedule")
    if declared is not None:
        windows = [EvaluationWindow.from_dict(row) for row in _list(declared, "schedule", MAX_TASKS)]
    attempts = _attempts(payload, rows, fits, as_of)
    forecast_attempts = [ForecastAttempt(arm, attempt["available_at"], attempt["inverter_id"])
                         for attempt in attempts for arm in ARMS]
    evaluation = evaluate_forecasts(forecasts, actuals, windows, as_of=as_of, sources=ARMS,
                                    forecast_attempts=forecast_attempts,
                                    timezone_name=timezone_name)
    strata = _scheduled_strata(rows, forecasts, windows, actuals, as_of, timezone_name, attempts, forecast_attempts)
    return {"schema": SCHEMA, "input_sha256": _digest(payload), "as_of": as_of.isoformat(),
            "scope": "residual_stage_before_power_nowcast", "operational_use": False,
            "statistical_acceptance": "not_evaluated", "supports_activation": False,
            "schedule_status": "caller_declared_not_independently_verified" if declared is not None else "posthoc_task_schedule",
            "schedule_sha256": _digest([w.to_dict() for w in sorted(set(windows), key=lambda w: (w.cutoff, w.inverter_id, w.start))]),
            "actual_qualification": "caller_asserted_whole_interval_quality", "actual_counts": actual_counts,
            "fit_reports": fit_reports, "task_count": len(rows), "attempt_count": len(attempts),
            "attempts": _json_safe(attempts), "scoring_exclusions": dict(ignored),
            "strata": strata, "evaluation": evaluation, "daily_wins": _daily_wins(evaluation),
            "tasks": _json_safe(rows), "provenance": payload.get("provenance"),
            "limitations": ["No final HA forecast or power-nowcast comparison.",
                            "Support guards cannot detect all changes in the target relationship.",
                            "Task exposure is not unique measured energy or independent evidence.",
                            "No acceptance, seasonal validity or future coverage is established."]}


def frozen_from_events(events, event_ids, *, as_of, actuals=(), schedule=None):
    """Import exported native envelopes without opening or modifying an archive.

    Required state and weather chunks must be present in the supplied export.
    Checksums establish integrity only; this is not exact-software replay acceptance.
    """
    unique = {}
    for event in _list(events, "events", 100_000):
        source = event.get("source")
        if source is not None:
            _identifier(source)
        validate_envelope({key: value for key, value in event.items() if key != "source"})
        key = (source, event["generation"], event["sequence"])
        if key in unique and canonical_bytes(unique[key]) != canonical_bytes(event):
            raise ValueError("conflicting archive envelope")
        unique[key] = event
    events = list(unique.values())
    event_ids = list(dict.fromkeys(event_ids))
    if not event_ids:
        raise ValueError("explicit forecast event IDs required")
    fits, tasks, attempts, provenance, timezone_name, site_digest = {}, [], [], [], None, None
    producer_identity = None
    as_of = timestamp(as_of) if isinstance(as_of, str) else as_of
    for identifier in event_ids:
        matches = [e for e in events if e["event_id"] == identifier and e["kind"] == "forecast_issued"]
        if len(matches) != 1:
            raise ValueError("missing or ambiguous selected forecast event")
        event = hydrate_forecast(matches[0], events)
        # Identical numerical site configuration is not producer identity.
        # Unlabelled journal exports are bound to their original generation;
        # they cannot silently join a named source or another unknown journal.
        identity = (("source", event["source"]) if event.get("source") is not None
                    else ("unlabelled_generation", event["generation"]))
        if producer_identity is not None and producer_identity != identity:
            raise ValueError("different archive sources require separate analyses")
        producer_identity = identity
        payload = event["payload"]
        issue, receipt = timestamp(payload["issued_at"]), timestamp(event["received_at"])
        if not issue <= receipt <= as_of:
            raise ValueError("forecast cutoff/receipt exceeds analysis cutoff")
        site = SiteConfig.from_dict(payload["site"])
        digest = _digest(site.to_dict())
        if site_digest is not None and digest != site_digest:
            raise ValueError("different site configurations require separate analyses")
        site_digest = digest
        if timezone_name is not None and site.timezone != timezone_name:
            raise ValueError("mixed site timezones require separate analyses")
        timezone_name = site.timezone
        verified_weather = verify_weather_receipts(event, events)
        if any(timestamp(o["time"]) > issue for o in payload["observations"]):
            raise ValueError("observation follows forecast cutoff")
        state = reconstruct_state(event, events)
        fit = {"fit_as_of": state.get("fit_as_of"), "fit_samples": state["fit_samples"],
               "learner_available": state.get("learner_available", True),
               "output_caps_w": {stage.id: stage.output_cap_w for stage in site.inverters}}
        # An available but never fitted empty native learner has no fit cutoff.
        if fit["learner_available"] and fit["fit_as_of"] is None and not fit["fit_samples"]:
            fit["fit_as_of"] = issue.isoformat()
        fit_id = _digest(fit)
        fits[fit_id] = {"id": fit_id, **fit}
        if timestamp(payload["result"]["issued_at"]) != issue:
            raise ValueError("result issue differs from original calculation cutoff")
        attempts.extend({"issued_at": issue.isoformat(), "available_at": receipt.isoformat(), "inverter_id": stage.id}
                        for stage in site.inverters)
        for point in payload["result"]["points"]:
            tasks.append({"fit_id": fit_id, "issued_at": issue.isoformat(), "available_at": receipt.isoformat(),
                          **{key: point[key] for key in ("start", "end", "inverter_id", "baseline_w", "features")}})
        provenance.append({"event_id": identifier, "source": event.get("source"),
                           "input_sha256": _digest({"payload": payload, "state": state}),
                           "archived_software": payload["software"], "verified_weather_receipts": verified_weather,
                           "exact_original_replay_acceptance": "not_evaluated"})
    result = {"schema": SCHEMA, "timezone": timezone_name, "as_of": as_of.isoformat(),
              "fits": list(fits.values()), "tasks": tasks, "attempts": attempts, "actuals": list(actuals), "provenance": provenance}
    if schedule is not None:
        result["schedule"] = schedule
    return result
