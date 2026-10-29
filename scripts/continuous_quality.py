"""Bounded local source selection and independently dated Recorder quality.

No network calls, HA dependencies, attestation creation or future auto-renewal.
The caller archives the result alongside the unchanged raw Recorder capture.
"""
from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from custom_components.adaptive_solar.core import actual_quality  # noqa: E402
from custom_components.adaptive_solar.core.archive import canonical_bytes  # noqa: E402
from custom_components.adaptive_solar.core.replay import timestamp  # noqa: E402
from scripts import capture_actuals, qualify_actuals  # noqa: E402

MAX_BYTES = 512 * 1024 * 1024


def derive(store, raw, bindings):
    """Use retained originals, including contradictions.

    Caller holds the host writer lock or supplies a frozen local archive copy.
    """
    if not isinstance(bindings, dict) or bindings.get("schema") != actual_quality.CONTINUOUS_BINDINGS_SCHEMA:
        raise ValueError("Continuous capture requires explicit v2 source policy")
    rows = bindings.get("bindings")
    if not isinstance(rows, list) or len(rows) > actual_quality.MAX_BINDINGS:
        raise ValueError("Invalid source policy")
    as_of = datetime.now(UTC)
    capture_actuals.normalize_capture(raw, None, normalized_at=as_of)
    qualify_actuals._validate_existing_quality(raw, as_of=as_of, validation_time=as_of)
    if capture_actuals.utc(raw["retrieved_at"]) > as_of:
        raise ValueError("Future raw capture")
    start, end = capture_actuals.target_bounds(raw["raw"]["target_start"], raw["raw"]["target_end"])
    mappings = list(capture_actuals.parse_mapping({"mappings": raw["raw"]["mappings"]}))
    events, byte_count = [], 0

    def add(event):
        nonlocal byte_count
        byte_count += len(canonical_bytes(event))
        if len(events) >= actual_quality.MAX_EVENTS or byte_count > MAX_BYTES:
            raise ValueError("Quality selection exceeds bounded budget")
        events.append(event)

    for source in sorted({row["source"] for row in rows}):
        periods = [row for row in rows if row["source"] == source]
        anchors = {row["config_event_id"] for row in periods}
        for event in store.iter_events(source=source):
            if event["kind"] not in {"qualified_interval", "forecast_issued"}:
                continue
            if timestamp(event["received_at"]) > as_of:
                continue
            p = event["payload"]
            if event["kind"] == "qualified_interval":
                if timestamp(p["start"]) >= end or timestamp(p["end"]) <= start:
                    continue
            elif event["event_id"] not in anchors and not any(
                    timestamp(row["valid_from"]) <= timestamp(p["issued_at"]) < timestamp(row["valid_to"])
                    for row in periods):
                continue
            add(event)
    # Resolve only payload dependencies, after iter_events releases its lock.
    for event in list(events):
        ref = event["payload"].get("payload_ref") if event["kind"] == "forecast_issued" else None
        if ref:
            for part in store.resolve_events(ref["event_ids"], source=event["source"], generation=event["generation"]):
                add(part)
    report = actual_quality.build_quality(events, bindings, mappings, start=start, end=end,
                                          as_of=as_of)
    generated = timestamp(report["generated_at"])
    report.update(bindings=bindings, raw_capture_sha256=actual_quality.digest(raw),
                  implementation_sha256={path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                         for path in (Path(__file__), Path(actual_quality.__file__), Path(capture_actuals.__file__))})
    normalized = capture_actuals.normalize_capture(raw, report["quality"], normalized_at=generated)
    return {**normalized, "quality_derivation": report}


def main(argv=None):
    """Local rehearsal: no HA access, original archive/capture never overwritten."""
    import argparse
    import json
    import os
    import sqlite3
    import sys

    from custom_components.adaptive_solar.core.archive import ArchiveStore
    from scripts.replay_paths import validate_output, write_output

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--bindings", type=Path, required=True)
    parser.add_argument("--actual-capture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New derived capture including source policy and diagnostic report")
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        inputs = (args.bindings, args.actual_capture, Path(__file__), Path(actual_quality.__file__),
                  Path(capture_actuals.__file__), Path(qualify_actuals.__file__))
        validate_output(args.output, args.archive, inputs)
        if not (args.archive / "index.sqlite3").is_file():
            raise ValueError("An existing local archive is required")
        bindings, details = qualify_actuals._read_json(args.bindings, remaining=qualify_actuals.MAX_INPUT_BYTES)
        raw, _ = qualify_actuals._read_json(args.actual_capture, remaining=qualify_actuals.MAX_TOTAL_BYTES - details["bytes"])
        result = derive(ArchiveStore(args.archive), raw, bindings)
        write_output(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n", args.output, args.archive, inputs)
        print(json.dumps({"status": "local_quality_rehearsal", "accepted_records": len(result["normalization"]["records"]),
                          "excluded_records": len(result["normalization"]["excluded"])}))
        return 0
    except (ValueError, TypeError, KeyError, OSError, sqlite3.Error):
        print("Local quality rehearsal failed; check private inputs and archive evidence.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    # Support direct execution as well as python -m scripts.continuous_quality.
    raise SystemExit(main())
