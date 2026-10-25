#!/usr/bin/env python3
"""Read-only HA Recorder actuals capture, with explicit quality evidence.

Verified against HA 2026.10.3 recorder/websocket_api.py and statistics.py:
* recorder/statistics_during_period, period=hour, types=[change], units.energy=kWh
* native WebSocket start/end timestamps are UNIX MILLISECONDS; the internal
  Python statistics function returns seconds before the WS adapter multiplies.
* change is interval energy; cumulative sum is never treated as interval energy.

Private mapping below ignored data/:
{"mappings": [{"inverter_id": "roof", "statistic_ids": ["sensor.PRIVATE"]}]}
Several statistic_ids may describe a physical site total, only with identical
complete intervals. Each statistic may be assigned to only one scope.

Optional private quality file:
{"schema_version": 1, "validated": true,
 "provenance": {"source": "verified evidence reference", "validated_at": "...+00:00"},
 "intervals": [{"inverter_id": "roof", "start": "...+00:00", "end": "...+00:00",
                "quality": "valid", "complete_coverage": true,
                "curtailed": false, "counter_reset": false}]}
A quality interval asserts evidence over its ENTIRE duration. Mask truth cannot
be established from the hourly statistics themselves. Unknown coverage,
curtailment or resets never become accepted labels. No mask means raw-only.

Raw responses and masks are retained separately from derived normalization.
Later Recorder corrections remain separate captures. Conflicting revisions
require an explicit archive selection, never implicit last-wins replacement.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
import fcntl
import json
import math
import os
from pathlib import Path
import stat
import sys
from urllib.parse import urlsplit, urlunsplit
import uuid

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
COMMAND = "recorder/statistics_during_period"
ENERGY_FACTORS = {"Wh": 0.001, "kWh": 1.0, "MWh": 1000.0}
# HA EnergyConverter units describe metadata dimensions, not response scaling.
ENERGY_UNITS = frozenset({"J", "kJ", "MJ", "GJ", "mWh", "Wh", "kWh", "MWh", "GWh", "TWh", "cal", "kcal", "Mcal", "Gcal", "thm"})
MAX_DAYS = 32


class CaptureError(ValueError):
    """A sanitized error safe to print without identifiers or credentials."""


def energy_metadata(meta) -> bool:
    """Validate native/archived units without converting requested changes."""
    if not meta or meta.get("has_sum") is not True or meta.get("unit_class") != "energy":
        return False
    stored = [meta[key] for key in ("statistics_unit_of_measurement", "unit_of_measurement") if key in meta]
    display = [meta["display_unit_of_measurement"]] if "display_unit_of_measurement" in meta else []
    return bool(stored) and all(isinstance(unit, str) and unit in ENERGY_UNITS for unit in stored + display) and len(set(stored)) == 1


def utc(value) -> datetime:
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
        if not isinstance(parsed, datetime) or parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
        return parsed.astimezone(UTC)
    except (TypeError, ValueError, OverflowError) as exc:
        raise CaptureError("Timestamps must be aware ISO-8601 values") from exc


def target_bounds(start, end) -> tuple[datetime, datetime]:
    start, end = utc(start), utc(end)
    if any(value.minute or value.second or value.microsecond for value in (start, end)):
        raise CaptureError("Targets must use complete UTC hour boundaries")
    if not start < end <= start + timedelta(days=MAX_DAYS):
        raise CaptureError("Target range must be positive and at most 32 days")
    return start, end


def parse_mapping(payload) -> tuple[dict, ...]:
    if not isinstance(payload, dict) or set(payload) != {"mappings"} or not isinstance(payload["mappings"], list) or not payload["mappings"]:
        raise CaptureError("Mapping requires a nonempty mappings list")
    groups, scopes, identifiers = [], set(), set()
    for row in payload["mappings"]:
        if not isinstance(row, dict) or set(row) != {"inverter_id", "statistic_ids"}:
            raise CaptureError("Each mapping requires inverter_id and statistic_ids")
        scope, ids = row["inverter_id"], row["statistic_ids"]
        if not isinstance(scope, str) or not scope.strip() or scope != scope.strip() or scope in scopes:
            raise CaptureError("Inverter scopes must be unique nonempty strings")
        if not isinstance(ids, list) or not ids or any(not isinstance(key, str) or not key.strip() or key != key.strip() for key in ids):
            raise CaptureError("statistic_ids must be nonempty strings")
        if len(set(ids)) != len(ids) or identifiers.intersection(ids):
            raise CaptureError("A statistic may be assigned only once")
        groups.append({"inverter_id": scope, "statistic_ids": list(ids)})
        scopes.add(scope)
        identifiers.update(ids)
    return tuple(groups)


def parse_quality(payload, *, normalized_at: datetime) -> tuple[list[dict], dict | None]:
    if payload is None:
        return [], None
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "validated", "provenance", "intervals"}:
        raise CaptureError("Malformed quality evidence envelope")
    provenance = payload["provenance"]
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1 or payload["validated"] is not True:
        raise CaptureError("Quality evidence must be explicitly validated")
    if not isinstance(provenance, dict) or set(provenance) != {"source", "validated_at"} or not isinstance(provenance["source"], str) or not provenance["source"].strip():
        raise CaptureError("Quality evidence needs a source and validation timestamp")
    validated = utc(provenance["validated_at"])
    if validated > normalized_at:
        raise CaptureError("Quality evidence validation lies in the future")
    if not isinstance(payload["intervals"], list):
        raise CaptureError("Quality intervals must be a list")
    parsed = []
    for row in payload["intervals"]:
        if not isinstance(row, dict) or set(row) != {"inverter_id", "start", "end", "quality", "complete_coverage", "curtailed", "counter_reset"}:
            raise CaptureError("Quality intervals require explicit coverage, curtailment and reset evidence")
        if not isinstance(row["inverter_id"], str) or not row["inverter_id"].strip() or not isinstance(row["quality"], str) or row["quality"] not in {"valid", "invalid", "unknown"}:
            raise CaptureError("Invalid quality interval scope or status")
        if type(row["complete_coverage"]) is not bool or any(value is not None and type(value) is not bool for value in (row["curtailed"], row["counter_reset"])):
            raise CaptureError("Quality flags must be explicit booleans or unknown")
        start, end = utc(row["start"]), utc(row["end"])
        if not start < end <= validated:
            raise CaptureError("Quality evidence must follow its complete measured interval")
        if any(old["inverter_id"] == row["inverter_id"] and start < old["end"] and old["start"] < end for old in parsed):
            raise CaptureError("Quality masks must not overlap for the same inverter")
        parsed.append({**row, "start": start, "end": end})
    return parsed, {**provenance, "validated_at": validated.isoformat()}


def _finite(value) -> bool:
    try:
        return not isinstance(value, bool) and isinstance(value, (float, int)) and math.isfinite(value)
    except OverflowError:
        return False


def _json_safe(value):
    """JSON cannot represent NaN/Infinity: preserve them as explicit nulls."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _request(mappings, start, end, unit="kWh") -> dict:
    return {"id": 2, "type": COMMAND, "statistic_ids": sorted({key for row in mappings for key in row["statistic_ids"]}),
            "start_time": (start - timedelta(hours=1)).isoformat(), "end_time": end.isoformat(),
            "period": "hour", "types": ["change"], "units": {"energy": unit}}


def build_raw_capture(metadata, statistics, mappings, start, end, retrieved_at) -> dict:
    """Archive only the selected statistics, preserving original protocol units."""
    mappings = parse_mapping({"mappings": list(mappings)})
    start, end = target_bounds(start, end)
    received = utc(retrieved_at)
    if not isinstance(metadata, list) or not isinstance(statistics, dict):
        raise CaptureError("Recorder metadata and statistics have unexpected shapes")
    selected = {key for mapping in mappings for key in mapping["statistic_ids"]}
    raw = {"request": _request(mappings, start, end), "target_start": start.isoformat(), "target_end": end.isoformat(),
           "mappings": list(mappings), "timestamp_unit": "milliseconds",
           "metadata": [row for row in metadata if isinstance(row, dict) and isinstance(row.get("statistic_id"), str) and row["statistic_id"] in selected],
           "statistics": {key: value for key, value in statistics.items() if key in selected}}
    return {"schema_version": 1, "kind": "ha_actuals", "capture_id": str(uuid.uuid4()), "retrieved_at": received.isoformat(), "raw": _json_safe(raw)}


def normalize_capture(capture, quality=None, *, normalized_at=None) -> dict:
    """Derive ActualRecord dictionaries only from explicit whole-interval evidence.

    The requested extra predecessor hour prevents a change spanning a missing
    Recorder row from being assigned to one later hour. This check alone does
    not establish measurement coverage, so validated quality is also required.
    """
    if not isinstance(capture, dict) or type(capture.get("schema_version")) is not int or capture.get("schema_version") != 1 or capture.get("kind") != "ha_actuals":
        raise CaptureError("Unsupported actual capture schema")
    received = utc(capture.get("retrieved_at"))
    normalized = utc(normalized_at or datetime.now(UTC))
    if normalized < received:
        raise CaptureError("Normalization cannot precede capture receipt")
    raw = capture.get("raw")
    if not isinstance(raw, dict) or raw.get("timestamp_unit") != "milliseconds":
        raise CaptureError("Native Recorder WebSocket timestamps must use milliseconds")
    start, end = target_bounds(raw.get("target_start"), raw.get("target_end"))
    mappings = parse_mapping({"mappings": raw.get("mappings")})
    request = raw.get("request")
    if not isinstance(request, dict):
        raise CaptureError("Missing Recorder request provenance")
    unit = request.get("units", {}).get("energy") if isinstance(request.get("units"), dict) else None
    if not isinstance(unit, str) or unit not in ENERGY_FACTORS or request != _request(mappings, start, end, unit):
        raise CaptureError("Recorder request must explicitly select hourly energy change")
    masks, provenance = parse_quality(quality, normalized_at=normalized)
    metadata, statistics = raw.get("metadata"), raw.get("statistics")
    if not isinstance(metadata, list) or not isinstance(statistics, dict):
        raise CaptureError("Malformed Recorder capture content")
    metadata_by_id = {}
    for row in metadata:
        if not isinstance(row, dict) or not isinstance(row.get("statistic_id"), str) or row["statistic_id"] in metadata_by_id:
            raise CaptureError("Duplicate or malformed Recorder metadata")
        metadata_by_id[row["statistic_id"]] = row
    indexed = {}
    for statistic_id in request["statistic_ids"]:
        rows = statistics.get(statistic_id)
        if rows is None:
            indexed[statistic_id] = {}
            continue
        if not isinstance(rows, list):
            raise CaptureError("Recorder statistic rows must be a list")
        series = {}
        for row in rows:
            if not isinstance(row, dict) or not _finite(row.get("start")) or not _finite(row.get("end")):
                raise CaptureError("Recorder timestamps must be finite native millisecond values")
            try:
                a, b = (datetime.fromtimestamp(row[key] / 1000, UTC) for key in ("start", "end"))
            except (ValueError, OSError, OverflowError) as exc:
                raise CaptureError("Recorder timestamp is invalid") from exc
            if a.minute or a.second or a.microsecond or b - a != timedelta(hours=1) or not start - timedelta(hours=1) <= a < end:
                raise CaptureError("Recorder rows must match requested complete UTC hours")
            if a in series:
                raise CaptureError("Recorder returned duplicate hourly rows")
            series[a] = row
        indexed[statistic_id] = series
    records, excluded = [], []
    hour = start
    while hour < end:
        stop = hour + timedelta(hours=1)
        for mapping in mappings:
            scope = mapping["inverter_id"]
            reasons = set()
            values = []
            if stop > received:
                reasons.add("future_or_unfinished_at_receipt")
            for key in mapping["statistic_ids"]:
                meta, series = metadata_by_id.get(key), indexed[key]
                if not energy_metadata(meta):
                    reasons.add("unverified_energy_metadata")
                row, previous = series.get(hour), series.get(hour - timedelta(hours=1))
                if row is None:
                    reasons.add("missing_statistic_hour")
                else:
                    change = row.get("change")
                    if not _finite(change) or change < 0:
                        reasons.add("invalid_or_negative_change")
                    else:
                        values.append(change * ENERGY_FACTORS[unit])
                if previous is None or not _finite(previous.get("change")) or previous["change"] < 0:
                    reasons.add("missing_or_invalid_predecessor")
            matching = [mask for mask in masks if mask["inverter_id"] == scope and mask["start"] <= hour and stop <= mask["end"]]
            if not matching:
                reasons.add("missing_quality_evidence")
            else:
                mask = matching[0]
                if mask["quality"] != "valid" or mask["complete_coverage"] is not True:
                    reasons.add("unverified_measurement_coverage")
                if mask["curtailed"] is None:
                    reasons.add("unknown_curtailment")
                elif mask["curtailed"]:
                    reasons.add("curtailed")
                if mask["counter_reset"] is None:
                    reasons.add("unknown_counter_reset")
                elif mask["counter_reset"]:
                    reasons.add("counter_reset")
            if not reasons:
                energy = sum(values)
                if not math.isfinite(energy) or not math.isfinite(energy * 1000):
                    reasons.add("nonfinite_aggregate_energy")
            if reasons:
                excluded.append({"inverter_id": scope, "start": hour.isoformat(), "end": stop.isoformat(), "reasons": sorted(reasons)})
            else:
                observed = max(received, utc(provenance["validated_at"]))
                records.append({"start": hour.isoformat(), "end": stop.isoformat(), "inverter_id": scope, "power_w": energy * 1000, "observed_at": observed.isoformat(), "curtailed": False})
        hour = stop
    return {**capture, "quality": quality, "normalized_at": normalized.isoformat(),
            "normalization": {"records": records, "excluded": excluded, "quality_provenance": provenance}}


def actual_records_from_captures(captures, *, as_of=None) -> list[dict]:
    """Keep source-revision time separate from evidence availability.

    Raw errors are known at receipt, quality errors only when their evidence is
    known. A late quality check never makes an old raw response a newer source
    revision. Identical accepted values may select a newer raw revision, while
    retaining that revision's own effective observed_at (never backdated).
    """
    selected = {}
    selected_receipts = {}
    invalid_revisions = {}
    invalid_quality = {}
    cutoff = utc(as_of) if as_of is not None else None
    for capture in captures:
        if not isinstance(capture, dict) or "normalized_at" not in capture or "normalization" not in capture:
            raise CaptureError("Actual capture must contain explicit normalization")
        verified = normalize_capture(capture, capture.get("quality"), normalized_at=capture["normalized_at"])
        if verified["normalization"] != capture["normalization"]:
            raise CaptureError("Actual records differ from raw capture and quality evidence")
        received = utc(capture["retrieved_at"])
        quality_known = max(received, utc(verified["normalization"]["quality_provenance"]["validated_at"]) if verified["normalization"]["quality_provenance"] else received)
        quality_reasons = {"missing_quality_evidence", "unverified_measurement_coverage",
                           "unknown_curtailment", "curtailed", "unknown_counter_reset", "counter_reset"}
        for excluded in verified["normalization"]["excluded"]:
            reasons = set(excluded["reasons"])
            key = (excluded["inverter_id"], excluded["start"], excluded["end"])
            if reasons - quality_reasons and (cutoff is None or received <= cutoff):
                invalid_revisions.setdefault(key, []).append(received)
            if reasons & (quality_reasons - {"missing_quality_evidence"}) and (cutoff is None or quality_known <= cutoff):
                invalid_quality.setdefault(key, []).append(quality_known)
        for row in verified["normalization"]["records"]:
            if cutoff is not None and utc(row["observed_at"]) > cutoff:
                continue
            key = (row["inverter_id"], row["start"], row["end"])
            previous = selected.get(key)
            if previous is not None:
                if row["power_w"] != previous["power_w"] or row["curtailed"] != previous["curtailed"]:
                    raise CaptureError("Conflicting actual revisions require explicit archive selection")
                if (received < selected_receipts[key]
                        or received == selected_receipts[key] and utc(row["observed_at"]) >= utc(previous["observed_at"])):
                    continue
            selected[key] = row
            selected_receipts[key] = received
    for key, row in selected.items():
        if (any(stamp >= selected_receipts[key] for stamp in invalid_revisions.get(key, ()))
                or any(stamp >= utc(row["observed_at"]) for stamp in invalid_quality.get(key, ()))):
            raise CaptureError("A later invalid actual revision conflicts with an accepted interval")
    return [selected[key] for key in sorted(selected)]


def websocket_url(ha_url: str) -> str:
    try:
        parsed = urlsplit(ha_url)
        if parsed.scheme not in {"http", "https", "ws", "wss"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError
        _ = parsed.port
        path = parsed.path.rstrip("/")
        if not path.endswith("/api/websocket"):
            path += "/api/websocket"
        return urlunsplit(("wss" if parsed.scheme in {"https", "wss"} else "ws", parsed.netloc, path, "", ""))
    except (ValueError, TypeError) as exc:
        raise CaptureError("HA_URL must be a base URL without credentials or query") from exc


async def capture_actuals(ha_url, token, mappings, start, end, *, timeout=30, session=None) -> dict:
    """Fetch only metadata and hourly change; never mutate HA state or statistics."""
    if not isinstance(token, str) or not token.strip():
        raise CaptureError("HA_TOKEN is required")
    if not _finite(timeout) or not 0 < timeout <= 120:
        raise CaptureError("Timeout must be between zero and 120 seconds")
    mappings = parse_mapping({"mappings": list(mappings)})
    start, end = target_bounds(start, end)
    if end > datetime.now(UTC):
        raise CaptureError("Actual capture target must already have ended")
    url = websocket_url(ha_url)

    async def request(client):
        async with asyncio.timeout(timeout):
            async with client.ws_connect(url, max_msg_size=8 * 1024 * 1024) as ws:
                hello = await ws.receive_json()
                if not isinstance(hello, dict) or hello.get("type") != "auth_required":
                    raise CaptureError("Unexpected HA authentication handshake")
                await ws.send_json({"type": "auth", "access_token": token})
                auth = await ws.receive_json()
                if not isinstance(auth, dict) or auth.get("type") != "auth_ok":
                    raise CaptureError("HA authentication failed")
                async def command(payload):
                    await ws.send_json(payload)
                    response = await ws.receive_json()
                    received = datetime.now(UTC)
                    if not isinstance(response, dict) or response.get("type") != "result" or type(response.get("id")) is not int or response["id"] != payload["id"] or response.get("success") is not True or "result" not in response:
                        raise CaptureError("HA read-only Recorder request failed")
                    return response["result"], received
                metadata, _ = await command({"id": 1, "type": "recorder/list_statistic_ids", "statistic_type": "sum"})
                statistics, received = await command(_request(mappings, start, end))
                capture = build_raw_capture(metadata, statistics, mappings, start, end, received)
                encoded = json.dumps(capture, ensure_ascii=False, allow_nan=False)
                if token in encoded or ha_url in encoded:
                    raise CaptureError("Response contained private connection credentials")
                return capture
    try:
        if session is not None:
            return await request(session)
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as client:
            return await request(client)
    except CaptureError:
        raise
    except (aiohttp.ClientError, TimeoutError, ValueError, TypeError, OverflowError) as exc:
        raise CaptureError("HA actual capture transport failed or exceeded its deadline") from exc


def append_capture(output: Path, capture: dict) -> None:
    encoded = (json.dumps(capture, ensure_ascii=False, allow_nan=False) + "\n").encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(output, os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise CaptureError("Actual capture output is locked by another writer") from exc
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise CaptureError("Actual capture output must be a regular file")
        if metadata.st_size and os.pread(descriptor, 1, metadata.st_size - 1) != b"\n":
            raise CaptureError("Existing actual capture ends with an incomplete record")
        position = 0
        while position < len(encoded):
            count = os.write(descriptor, encoded[position:])
            if count <= 0:
                raise CaptureError("Actual capture append was incomplete")
            position += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _private_path(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to((ROOT / "data").resolve()):
        raise CaptureError("Private configuration, quality and output must stay below ignored data/")
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--quality", type=Path)
    parser.add_argument("--start", required=True, help="Aware ISO timestamp, complete UTC hour")
    parser.add_argument("--end", required=True, help="Exclusive aware ISO timestamp, complete UTC hour")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    try:
        config, output = _private_path(args.config), _private_path(args.output)
        quality_path = _private_path(args.quality) if args.quality else None
        for source in (config, quality_path):
            if source is not None and (source == output or source.exists() and output.exists() and os.path.samefile(source, output)):
                raise CaptureError("Actual capture output must differ from every input")
        mappings = parse_mapping(json.loads(config.read_text(encoding="utf-8")))
        quality = json.loads(quality_path.read_text(encoding="utf-8")) if quality_path else None
        capture = asyncio.run(capture_actuals(os.environ.get("HA_URL", ""), os.environ.get("HA_TOKEN", ""), mappings, args.start, args.end, timeout=args.timeout))
        normalized = normalize_capture(capture, quality)
        encoded = json.dumps(normalized, ensure_ascii=False, allow_nan=False)
        token = os.environ.get("HA_TOKEN", "")
        if token and token in encoded:
            raise CaptureError("Private credentials must not occur in capture or quality evidence")
        append_capture(output, normalized)
    except (CaptureError, OSError, json.JSONDecodeError) as exc:
        print(str(exc) if isinstance(exc, CaptureError) else "Actual capture input/output failed", file=sys.stderr)
        return 2
    result = normalized["normalization"]
    print(f"Actual capture appended: {len(result['records'])} accepted, {len(result['excluded'])} excluded intervals")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
