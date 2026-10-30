#!/usr/bin/env python3
"""Evaluate a frozen residual-support candidate without network or archive writes.

Input is either the versioned frozen evaluation contract, or an exported JSON
array of original forecast/state/weather envelopes with explicit forecast IDs.
All output is descriptive and cannot authorize productive model activation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.adaptive_solar.archive_export import software_provenance
from custom_components.adaptive_solar.core.archive import canonical_bytes
from custom_components.adaptive_solar.core.replay import timestamp
from custom_components.adaptive_solar.core.support_evaluation import evaluate_support, frozen_from_events
from scripts.replay_paths import validate_output, write_output

MAX_INPUT_BYTES = 128 * 1024 * 1024


def read_json(path):
    with path.open("rb") as stream:
        raw = stream.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("input exceeds byte bound")
    value = json.loads(raw)
    canonical_bytes(value)
    return value, hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path, help="Frozen adaptive-solar-support-evaluation-v1 JSON")
    source.add_argument("--events-json", type=Path, help="Exported original native envelopes, same configured site")
    parser.add_argument("--event-id", action="append", default=[], help="Explicit forecast ID; repeat for several origins")
    parser.add_argument("--as-of", type=timestamp, help="Analysis/label availability cutoff for native events")
    parser.add_argument("--actuals-json", type=Path, help="Explicitly qualified ActualRecord array for native events")
    parser.add_argument("--schedule-json", type=Path, help="Declared EvaluationWindow array for native events")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    input_path = args.input or args.events_json
    inputs = (input_path, args.actuals_json, args.schedule_json, Path(__file__))
    try:
        validate_output(args.output, input_path, inputs)
        value, digest = read_json(input_path)
        hashes = {"input": digest}
        if args.input:
            if args.event_id or args.as_of is not None or args.actuals_json or args.schedule_json:
                raise ValueError("native options cannot override a frozen input contract")
            payload = value
        else:
            if not args.event_id or args.as_of is None:
                raise ValueError("native input requires event IDs and explicit as-of")
            actuals, schedule = [], None
            if args.actuals_json:
                actuals, hashes["actuals"] = read_json(args.actuals_json)
            if args.schedule_json:
                schedule, hashes["schedule"] = read_json(args.schedule_json)
            payload = frozen_from_events(value, args.event_id, as_of=args.as_of, actuals=actuals, schedule=schedule)
        report = evaluate_support(payload)
        report.update(input_file_sha256=hashes, analysis_software=software_provenance(),
                      analysis_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        write_output(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n",
                     args.output, input_path, inputs)
        print(json.dumps({"status": "diagnostic_only", "tasks": report["task_count"],
                          "paired_tasks": report["evaluation"]["paired_intervals"], "output": str(args.output)}))
        return 0
    except (ValueError, OSError, TypeError, KeyError, AttributeError) as err:
        # Do not print arbitrary private source values from parser exceptions.
        print(f"Support analysis failed: {type(err).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
