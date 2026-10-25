#!/usr/bin/env python3
"""Evaluate a declared common schedule from archived forecast/actual JSON rows."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.adaptive_solar.core.evaluation import (
    ActualRecord, EvaluationWindow, ForecastRecord, evaluate_forecasts,
)
from custom_components.adaptive_solar.core.statistical_validation import paired_day_bootstrap
from scripts.capture_actuals import actual_records_from_captures


def _receipt(value):
    if not isinstance(value, str):
        raise ValueError("Capture receipt must be an ISO timestamp")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Capture receipt must be timezone aware")
    return parsed.astimezone(timezone.utc)


def forecast_records_from_captures(captures, windows):
    """Normalize captures and preserve newer unavailable issues explicitly.

    A source outage has no measured forecast value. A null sentinel for every
    matching declared target makes that observed unavailable issue visible to
    the evaluator's newest-issue selection, preventing older-success fallback.
    The sentinel is never a zero prediction and never enters paired scores.
    """
    records = []
    windows = tuple(windows)
    unavailable = {"missing_entries", "invalid_entries", "incompatible_hours", "empty_forecast",
                   "missing_entity", "invalid_entity", "unavailable_entity"}
    for captured in captures:
        if (not isinstance(captured, dict) or type(captured.get("schema_version")) is not int
                or captured["schema_version"] != 1 or not isinstance(captured.get("groups"), list)):
            raise ValueError("Unsupported or malformed capture schema")
        seen = set()
        for group in captured["groups"]:
            if not isinstance(group, dict):
                raise ValueError("Malformed capture group")
            source, inverter = group.get("source"), group.get("inverter_id")
            if (not isinstance(source, str) or source not in {"adaptive", "helios", "open_meteo"}
                    or not isinstance(inverter, str) or not inverter.strip()):
                raise ValueError("Malformed capture source/inverter scope")
            if (source, inverter) in seen:
                raise ValueError("Duplicate source/inverter group in capture")
            seen.add((source, inverter))
            issued, retrieved = _receipt(group.get("issued_at")), _receipt(group.get("retrieved_at"))
            if issued != retrieved:
                raise ValueError("Capture issue must be its actual local receipt")
            rows, status = group.get("records"), group.get("status")
            if not isinstance(rows, list) or status not in unavailable | {"available"}:
                raise ValueError("Malformed capture group availability")
            if status != "available" and rows:
                raise ValueError("Unavailable capture group must not contain forecast values")
            if not rows:
                for window in windows:
                    if window.inverter_id == inverter:
                        records.append(ForecastRecord(source, issued, window.start, window.end, inverter, None))
                continue
            previous_end = None
            for row in rows:
                if (not isinstance(row, dict) or row.get("source") != source or row.get("inverter_id") != inverter
                        or _receipt(row.get("issued_at")) != issued or _receipt(row.get("retrieved_at")) != retrieved):
                    raise ValueError("Capture row differs from its source/scope/receipt")
                start, end = _receipt(row.get("start")), _receipt(row.get("end"))
                power, energy = row.get("power_w"), row.get("energy_wh")
                if any(isinstance(value, bool) or not isinstance(value, (int, float))
                       or not math.isfinite(value) or value < 0 for value in (power, energy)):
                    raise ValueError("Capture forecast values must be finite and nonnegative")
                if end <= start or previous_end is not None and start < previous_end:
                    raise ValueError("Capture intervals must be ordered and nonoverlapping")
                if not math.isclose(energy, power * (end - start).total_seconds() / 3600,
                                    rel_tol=1e-6, abs_tol=0.06):
                    raise ValueError("Capture energy differs from interval mean power")
                records.append(ForecastRecord(source, issued, start, end, inverter, power))
                previous_end = end
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--captures", type=Path, help="Read-only capture JSONL, preserving unavailable issues")
    parser.add_argument("--actual-captures", type=Path, help="Read-only validated Recorder actual-capture JSONL")
    parser.add_argument("--bootstrap", action="store_true", help="Run conditional paired target-day statistical policy v1")
    parser.add_argument("--bootstrap-resamples", type=int, default=20000, help="Minimum resamples; declared family may require more")
    parser.add_argument("--bootstrap-seed", type=int, default=20261024)
    parser.add_argument("--bootstrap-confidence", type=float, default=0.95, help="Nominal family confidence, at least 0.95")
    args = parser.parse_args()
    for source in (args.input, args.captures, args.actual_captures):
        if source is not None and (args.output.resolve() == source.resolve()
                or args.output.exists() and source.exists() and args.output.samefile(source)):
            parser.error("evaluation output must not overwrite an input archive")
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Evaluation input must be an object")
        for field in ("windows", "forecasts", "actuals", "sources"):
            if field in payload and not isinstance(payload[field], list):
                raise ValueError(f"Evaluation {field} must be a list")
        as_of = _receipt(payload["as_of"])
        sources = tuple(payload.get("sources", ("adaptive", "physics", "helios", "open_meteo")))
        windows = [EvaluationWindow.from_dict(row) for row in payload["windows"]]
        forecasts = [ForecastRecord.from_dict(row) for row in payload.get("forecasts", [])]
        if args.captures:
            # Every line must be complete JSON. Blank lines are errors too.
            with args.captures.open(encoding="utf-8") as archive:
                forecasts.extend(forecast_records_from_captures((json.loads(line) for line in archive), windows))
        elif "forecasts" not in payload:
            raise ValueError("input requires forecasts or --captures")
        actuals = [ActualRecord.from_dict(row) for row in payload.get("actuals", [])]
        if args.actual_captures:
            with args.actual_captures.open(encoding="utf-8") as archive:
                normalized = actual_records_from_captures((json.loads(line) for line in archive), as_of=as_of)
                actuals.extend(ActualRecord.from_dict(row) for row in normalized)
        elif "actuals" not in payload:
            raise ValueError("input requires actuals or --actual-captures")
        report = evaluate_forecasts(forecasts, actuals, windows, as_of=as_of, sources=sources,
                                    timezone_name=payload.get("timezone_name", "UTC"))
        if args.bootstrap:
            report["statistical_acceptance"] = paired_day_bootstrap(
                report, n_resamples=args.bootstrap_resamples, seed=args.bootstrap_seed,
                confidence_level=args.bootstrap_confidence)
        encoded = json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    except (OSError, KeyError, TypeError, ValueError, OverflowError) as error:
        parser.error(f"Invalid evaluation input or policy: {error}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded, encoding="utf-8")
    print(f"{report['paired_intervals']}/{report['expected_intervals']} paired intervals; "
          f"comparison eligible: {report['comparison_eligible']}")


if __name__ == "__main__":
    main()
