#!/usr/bin/env python3
"""Archive selected HA reference forecasts and Recorder revisions without HA writes."""
from __future__ import annotations

import argparse
import asyncio
import base64
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from custom_components.adaptive_solar.core.archive import ArchiveError, ArchiveJournal, ArchiveStore, canonical_bytes  # noqa: E402
from scripts import capture_actuals, capture_ha  # noqa: E402
from scripts.archive import collect, producer_status  # noqa: E402

CHUNK_BYTES = 256 * 1024
MAX_CAPTURE_BYTES = 32 * 1024 * 1024


def actual_window(now, *, lookback_hours=72, lag_minutes=10):
    """Only complete UTC hours; lag avoids treating Recorder publication as instant."""
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ArchiveError("Current time must be timezone aware")
    if type(lookback_hours) is not int or not 1 <= lookback_hours <= 24 * 31:
        raise ArchiveError("lookback_hours must be between 1 and 744")
    if type(lag_minutes) is not int or not 0 <= lag_minutes <= 120:
        raise ArchiveError("lag_minutes must be between 0 and 120")
    end = (now.astimezone(UTC) - timedelta(minutes=lag_minutes)).replace(minute=0, second=0, microsecond=0)
    return end - timedelta(hours=lookback_hours), end


def append_capture(journal, kind, capture):
    """Commit lossless chunks and manifest together, with no orphan on interruption."""
    if kind not in {"actuals", "references"} or not isinstance(capture, dict):
        raise ArchiveError("Unsupported observation capture")
    identifier = capture.get("capture_id")
    if not isinstance(identifier, str) or not identifier:
        raise ArchiveError("Capture ID required")
    received = capture.get("retrieved_at")
    try:
        stamp = datetime.fromisoformat(received)
    except (TypeError, ValueError) as exc:
        raise ArchiveError("Capture receipt required") from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ArchiveError("Capture receipt must be timezone aware")
    raw = canonical_bytes(capture)
    if len(raw) > MAX_CAPTURE_BYTES:
        raise ArchiveError("Observation capture exceeds bounded archive size")
    digest = hashlib.sha256(raw).hexdigest()
    chunks = []
    events = []
    for index, offset in enumerate(range(0, len(raw), CHUNK_BYTES)):
        part = raw[offset:offset + CHUNK_BYTES]
        chunk_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"adaptive-solar:{kind}:{identifier}:{index}:{digest}"))
        part_hash = hashlib.sha256(part).hexdigest()
        events.append(("observation_capture_chunk", {
            "capture_id": identifier, "capture_kind": kind, "index": index,
            "sha256": part_hash, "data_base64": base64.b64encode(part).decode("ascii"),
        }, stamp, chunk_id))
        chunks.append({"event_id": chunk_id, "sha256": part_hash})
    events.append(("observation_capture", {
        "capture_id": identifier, "capture_kind": kind, "sha256": digest,
        "size_bytes": len(raw), "chunks": chunks,
    }, stamp, str(uuid.uuid5(uuid.NAMESPACE_URL, f"adaptive-solar:{kind}:{identifier}:{digest}"))))
    return journal.append_many(events)[-1]


def captures_from_archive(store, *, source, kind, dataset=None):
    """Yield original capture objects for the existing actual/reference evaluators."""
    if kind not in {"actuals", "references"}:
        raise ArchiveError("Unsupported capture kind")
    parts = {}
    total = 0
    options = {"source": source}
    if dataset is not None:
        options["dataset"] = dataset
    for event in store.iter_events(**options):
        row = event["payload"]
        if row.get("capture_kind") != kind:
            continue
        if event["kind"] == "observation_capture_chunk":
            try:
                data = base64.b64decode(row["data_base64"], validate=True)
            except (KeyError, TypeError, ValueError) as exc:
                raise ArchiveError("Malformed observation chunk") from exc
            if len(data) > CHUNK_BYTES or hashlib.sha256(data).hexdigest() != row.get("sha256"):
                raise ArchiveError("Observation chunk digest mismatch")
            old = parts.get(event["event_id"])
            if old is not None and old != data:
                raise ArchiveError("Conflicting observation chunk")
            if old is None:
                total += len(data)
            parts[event["event_id"]] = data
            if total > MAX_CAPTURE_BYTES:
                raise ArchiveError("Incomplete observation captures exceed reconstruction budget")
        elif event["kind"] == "observation_capture":
            refs = row.get("chunks")
            if not isinstance(refs, list) or not refs or len(refs) > MAX_CAPTURE_BYTES // CHUNK_BYTES:
                raise ArchiveError("Malformed observation manifest")
            try:
                ids = [ref["event_id"] for ref in refs]
                if len(set(ids)) != len(ids):
                    raise ArchiveError("Duplicate observation chunk reference")
                selected = [parts[identifier] for identifier in ids]
                if any(hashlib.sha256(part).hexdigest() != ref["sha256"] for part, ref in zip(selected, refs, strict=True)):
                    raise ArchiveError("Observation manifest chunk digest mismatch")
                raw = b"".join(selected)
            except (KeyError, TypeError) as exc:
                raise ArchiveError("Observation capture has missing chunks") from exc
            if type(row.get("size_bytes")) is not int or len(raw) != row["size_bytes"] or hashlib.sha256(raw).hexdigest() != row.get("sha256"):
                raise ArchiveError("Observation manifest size or digest mismatch")
            capture = json.loads(raw)
            if not isinstance(capture, dict) or capture.get("capture_id") != row.get("capture_id"):
                raise ArchiveError("Observation manifest identity mismatch")
            for identifier in ids:
                total -= len(parts.pop(identifier))
            yield capture
    if parts:
        raise ArchiveError("Archive contains incomplete observation captures")


async def archive_observations(store, *, source, ha_url, token, actual_mappings=None,
                               reference_mappings=None, quality=None, cutoff=None, now=None,
                               lookback_hours=72, lag_minutes=10, timeout=30):
    """Independent streams preserve useful reads when another source fails."""
    if not actual_mappings and not reference_mappings:
        raise ArchiveError("At least one explicit observation mapping is required")
    if not isinstance(source, str) or not source.strip() or len(source) > 200:
        raise ArchiveError("A bounded stable source identity is required")
    report = {"streams": {}, "complete": True}
    for kind, mappings in (("actuals", actual_mappings), ("references", reference_mappings)):
        if not mappings:
            continue
        producer = f"{source}:{kind}"
        path = store.root / "staging" / hashlib.sha256(producer.encode()).hexdigest()
        try:
            journal = await asyncio.to_thread(ArchiveJournal, path)

            async def fetch(cursor):
                def read():
                    page = journal.page(cursor)
                    stats = journal.stats()
                    # Local append/read calls finish synchronously; unlike HA's
                    # exporter there is no asynchronous producer queue.
                    status = producer_status({"enabled": True, "state": "active", "last_error": None,
                        "dropped_events": stats["dropped_events"], "pending_events": 0, "inflight_events": 0})
                    return {"page": page, "producer": status}
                return await asyncio.to_thread(read)

            # Recover a locally committed prior capture even when HA is now offline.
            recovered = await collect(store, producer, fetch)
            if not recovered["complete"]:
                report["streams"][kind] = {"status": "recovery_incomplete", "recovery": recovered,
                                           "current_capture_confirmed": False}
                report["complete"] = False
                continue
            quality_error = False
            if kind == "actuals":
                start, end = actual_window(now or datetime.now(UTC), lookback_hours=lookback_hours, lag_minutes=lag_minutes)
                raw = await capture_actuals.capture_actuals(ha_url, token, mappings, start, end, timeout=timeout)
                try:
                    capture = await asyncio.to_thread(capture_actuals.normalize_capture, raw, quality)
                except capture_actuals.CaptureError:
                    # Keep the original Recorder revision even when a supplied mask is invalid.
                    capture = {**raw, "quality": quality, "normalization_error": "invalid_quality_or_raw"}
                    quality_error = True
            else:
                capture = await capture_ha.capture_forecasts(ha_url, token, mappings, timeout=timeout, cutoff=cutoff)
            if token and token in json.dumps(capture, ensure_ascii=False, allow_nan=False):
                raise ArchiveError("Response contained connection credentials")
            await asyncio.to_thread(append_capture, journal, kind, capture)

            result = await collect(store, producer, fetch)
            late = capture.get("cutoff_check", {}).get("late_group_count", 0)
            result.update(status="collection_incomplete" if not result["complete"] else
                          "invalid_quality_or_raw" if quality_error else "late" if late else "archived",
                          late_groups=late, recovered_events=recovered["events"],
                          current_capture_confirmed=result["complete"])
            if kind == "actuals" and not quality_error:
                normalized = capture["normalization"]
                result.update(accepted_intervals=len(normalized["records"]), excluded_intervals=len(normalized["excluded"]))
            report["streams"][kind] = result
            if quality_error or late or not result["complete"]:
                report["complete"] = False
        except (ArchiveError, capture_actuals.CaptureError, capture_ha.CaptureError, OSError, TimeoutError, ValueError, sqlite3.Error):
            # Do not print raw exceptions, entity names, transport URLs or tokens.
            report["streams"][kind] = {"status": "failed", "current_capture_confirmed": False}
            report["complete"] = False
    return report


def _private_path(path):
    resolved = path.resolve()
    if not resolved.is_relative_to((ROOT / "data").resolve()):
        raise ArchiveError("Private mappings and output must stay below ignored data/")
    return resolved


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--actual-config", type=Path)
    parser.add_argument("--reference-config", type=Path)
    parser.add_argument("--quality", type=Path, help="Explicit interval quality evidence; absent remains unknown")
    parser.add_argument("--cutoff", help="Aware fixed reference forecast deadline")
    parser.add_argument("--lookback-hours", type=int, default=72)
    parser.add_argument("--lag-minutes", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args(argv)
    try:
        def read(path):
            return json.loads(_private_path(path).read_text()) if path else None
        actual = capture_actuals.parse_mapping(read(args.actual_config)) if args.actual_config else None
        reference = capture_ha.parse_mapping(read(args.reference_config)) if args.reference_config else None
        cutoff = capture_ha._utc(datetime.fromisoformat(args.cutoff)) if args.cutoff else None
        report = asyncio.run(archive_observations(ArchiveStore(_private_path(args.archive)), source=args.source,
            ha_url=os.environ.get("HA_URL", ""), token=os.environ.get("HA_TOKEN", ""),
            actual_mappings=actual, reference_mappings=reference, quality=read(args.quality), cutoff=cutoff,
            lookback_hours=args.lookback_hours, lag_minutes=args.lag_minutes, timeout=args.timeout))
        print(json.dumps(report, sort_keys=True))
        return 0 if report["complete"] else 1
    except (ArchiveError, capture_actuals.CaptureError, capture_ha.CaptureError, OSError, ValueError, sqlite3.Error):
        print("Observation archive failed; check private mappings and archive status.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
