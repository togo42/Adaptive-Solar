#!/usr/bin/env python3
"""Derive Recorder quality evidence from local original archive envelopes.

This offline adapter never contacts HA and never changes original captures.
Its evidence cutoff can be historical; the new quality decision is always
dated at the real execution time and must not be backdated to that cutoff.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.adaptive_solar.core import actual_quality
from custom_components.adaptive_solar.core.archive import canonical_bytes
from scripts import capture_actuals
from scripts.replay_paths import validate_output, write_output

MAX_INPUT_BYTES = 128 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024


class ExistingQualityConflict(ValueError):
    """Existing negative evidence needs resolution outside this adapter."""


def _read_json(path, *, remaining):
    limit = min(MAX_INPUT_BYTES, remaining)
    if limit < 0:
        raise ValueError("aggregate input exceeds byte bound")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("input exceeds byte bound")
    value = json.loads(raw)
    canonical_bytes(value)
    return value, {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def _validate_outputs(outputs, inputs, capture_path):
    """Check all outputs together before writing and before each publication."""
    for index, output in enumerate(outputs):
        others = outputs[:index] + outputs[index + 1:]
        validate_output(output, capture_path, (*inputs, *others))
        if output.exists() and not output.is_file():
            raise ValueError("output must be a file")
        for other in others:
            lexical, other_lexical = Path(os.path.abspath(output)), Path(os.path.abspath(other))
            resolved, other_resolved = output.resolve(), other.resolve()
            if (lexical.is_relative_to(other_lexical) or other_lexical.is_relative_to(lexical)
                    or resolved.is_relative_to(other_resolved) or other_resolved.is_relative_to(resolved)):
                raise ValueError("output paths must be disjoint")


def _counts(normalization):
    return {"accepted_records": len(normalization["records"]),
            "excluded_records": len(normalization["excluded"]),
            "excluded_reasons": dict(Counter(reason for row in normalization["excluded"]
                                              for reason in row["reasons"]))}


def _validate_existing_quality(capture, *, as_of, validation_time):
    """Never turn an existing rejection into a new automatic qualification."""
    quality = capture.get("quality")
    masks, provenance = capture_actuals.parse_quality(quality, normalized_at=validation_time)
    if provenance is not None and capture_actuals.utc(provenance["validated_at"]) > as_of:
        raise ValueError("existing quality is unavailable at the evidence cutoff")
    if "normalized_at" in capture or "normalization" in capture:
        if "normalized_at" not in capture or "normalization" not in capture:
            raise ValueError("incomplete existing normalization metadata")
        original_time = capture_actuals.utc(capture["normalized_at"])
        if original_time > validation_time:
            raise ValueError("existing normalization is in the future")
        verified = capture_actuals.normalize_capture(capture, quality, normalized_at=original_time)
        if canonical_bytes(verified["normalization"]) != canonical_bytes(capture["normalization"]):
            raise ValueError("existing normalization disagrees with its original inputs")
    if any(capture_actuals._quality_rejections(mask) for mask in masks):
        raise ExistingQualityConflict


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events-json", type=Path, action="append", required=True,
                        help="Original source-tagged archive envelope array; repeat for several exports")
    parser.add_argument("--bindings", type=Path, required=True, help="Explicit private source/stage/statistic bindings")
    parser.add_argument("--actual-capture", type=Path, required=True, help="One original raw or normalized ha_actuals capture")
    parser.add_argument("--as-of", type=capture_actuals.utc, required=True, help="Latest evidence receipt allowed for qualification")
    parser.add_argument("--output", type=Path, required=True, help="New qualification report")
    parser.add_argument("--quality-output", type=Path, help="Optional separate compatible quality mask")
    parser.add_argument("--normalized-output", type=Path, help="Optional separately derived Recorder capture")
    args = parser.parse_args()
    outputs = [path for path in (args.output, args.quality_output, args.normalized_output) if path is not None]
    inputs = (*args.events_json, args.bindings, args.actual_capture, Path(__file__),
              Path(actual_quality.__file__), Path(capture_actuals.__file__))
    try:
        _validate_outputs(outputs, inputs, args.actual_capture)
        remaining, hashes, events = MAX_TOTAL_BYTES, [], []
        for index, path in enumerate(args.events_json):
            value, details = _read_json(path, remaining=remaining)
            remaining -= details["bytes"]
            if not isinstance(value, list):
                raise ValueError("event export must be an array")
            events.extend(value)
            hashes.append({"role": "events", "index": index, **details})
        bindings, details = _read_json(args.bindings, remaining=remaining)
        remaining -= details["bytes"]
        hashes.append({"role": "bindings", **details})
        capture, details = _read_json(args.actual_capture, remaining=remaining)
        hashes.append({"role": "actual_capture", **details})
        validation_time = datetime.now(UTC)
        if args.as_of > validation_time:
            raise ValueError("evidence cutoff cannot be in the future")
        # Validate the native request, timestamps, units and complete raw shape
        # before deriving any quality. Existing masks cannot release this path.
        raw_only = capture_actuals.normalize_capture(capture, None, normalized_at=validation_time)
        received = capture_actuals.utc(capture["retrieved_at"])
        if received > args.as_of:
            raise ValueError("raw capture follows evidence cutoff")
        _validate_existing_quality(capture, as_of=args.as_of, validation_time=validation_time)
        raw = capture["raw"]
        start, end = capture_actuals.target_bounds(raw["target_start"], raw["target_end"])
        mappings = list(capture_actuals.parse_mapping({"mappings": raw["mappings"]}))
        generated_at = datetime.now(UTC)
        report = actual_quality.build_quality(events, bindings, mappings, start=start, end=end,
                                              as_of=args.as_of, generated_at=generated_at)
        quality = report["quality"]
        if capture_actuals.utc(quality["provenance"]["validated_at"]) != generated_at:
            raise ValueError("derived quality must use the actual generation time")
        # Preserve the original raw capture and receipt. Superseded derived
        # metadata is not carried into a new independently dated normalization.
        original = {key: capture[key] for key in ("schema_version", "kind", "capture_id", "retrieved_at", "raw")}
        normalized = capture_actuals.normalize_capture(original, quality, normalized_at=generated_at)
        report = {**report, "generated_at": generated_at.isoformat(), "evidence_as_of": args.as_of.isoformat(),
                  "raw_retrieved_at": received.isoformat(), "input_files": hashes,
                  "adapter_source_sha256": hashlib.sha256(Path(actual_quality.__file__).read_bytes()).hexdigest(),
                  "normalizer_source_sha256": hashlib.sha256(Path(capture_actuals.__file__).read_bytes()).hexdigest(),
                  "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  "normalization_comparison": {"raw_without_quality": _counts(raw_only["normalization"]),
                                               "derived_quality": _counts(normalized["normalization"])},
                  "normalization": normalized["normalization"],
                  "normalized_capture_sha256": hashlib.sha256(canonical_bytes(normalized)).hexdigest(),
                  "operational_use": False}
        values = [(args.output, report)]
        if args.quality_output:
            values.append((args.quality_output, quality))
        if args.normalized_output:
            values.append((args.normalized_output, normalized))
        # Each file publishes atomically. This is not a multi-file transaction;
        # the content hashes permit a caller to detect a partial publication.
        for path, value in values:
            _validate_outputs(outputs, inputs, args.actual_capture)
            other_outputs = [other for other in outputs if other != path]
            write_output(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n",
                         path, args.actual_capture, (*inputs, *other_outputs))
        print(json.dumps({"status": "offline_quality_derived", "accepted_records": len(normalized["normalization"]["records"]),
                          "excluded_records": len(normalized["normalization"]["excluded"])}))
        return 0
    except ExistingQualityConflict:
        print("Existing quality rejects or leaves unknown intervals; separate explicit resolution is required.", file=sys.stderr)
        return 2
    except (ValueError, OSError, TypeError, KeyError, AttributeError) as err:
        # Arbitrary private entity values may appear in parser exceptions.
        print(f"Actual quality derivation failed: {type(err).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
