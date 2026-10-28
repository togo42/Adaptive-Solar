#!/usr/bin/env python3
"""Host-only original deterministic and real EPS capture; no HA writes.

Private coordinates/configuration belong in ignored data/. This command performs
one collection, making it suitable for a host timer without an in-process daemon.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sys
from uuid import uuid4

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.adaptive_solar.core.archive import ArchiveJournal, ArchiveStore
from custom_components.adaptive_solar.archive_export import software_provenance
from custom_components.adaptive_solar.core.ensemble import (
    DEFAULT_DETERMINISTIC, DEFAULT_ENSEMBLES, ENSEMBLE_COUNTS, ENSEMBLE_URL, FORECAST_URL,
    field_provenance, parse_members, request_params,
)
from custom_components.adaptive_solar.core.models import SiteConfig
from custom_components.adaptive_solar.weather import parse_forecast

MAX_RESPONSE_BYTES = 16 * 1024 * 1024
CHUNK_BYTES = 150_000


def flush_journal(journal, store, source):
    while True:
        page = journal.page(store.checkpoint(source), limit=100)
        store.ingest_page(source, page)
        if not page["events"]:
            break


def archive_response(journal, request, raw: bytes | None, received_at, *, product, ensemble,
                     http_status=None, error_type=None, site=None, truncated=False):
    """Preserve exact response bytes as bounded chunks before parsing a manifest."""
    group = str(uuid4())
    chunk_ids, batch = [], []
    digest = hashlib.sha256(raw).hexdigest() if raw is not None else None
    if raw is not None:
        count = max(1, (len(raw) + CHUNK_BYTES - 1) // CHUNK_BYTES)
        for index in range(count):
            data = raw[index * CHUNK_BYTES:(index + 1) * CHUNK_BYTES]
            event_id = str(uuid4())
            batch.append(("host_weather_response_chunk", {
                "group_id": group, "response_sha256": digest, "index": index, "count": count,
                "base64": base64.b64encode(data).decode("ascii"),
            }, received_at, event_id))
            chunk_ids.append(event_id)
    coverage = {}
    status = "failed"
    if error_type is None and not truncated and http_status == 200 and raw is not None:
        try:
            payload = json.loads(raw)
            if ensemble:
                parsed = parse_members(payload, product, received_at, site)
                coverage = {"expected_members": parsed.expected_members, "parsed_members": len(parsed.members),
                            "missing_members": list(parsed.missing_members),
                            "rejected_members": {str(key): value for key, value in parsed.rejected_members.items()},
                            "member_intervals": {member.model: len(member.points) for member in parsed.members}}
                if not parsed.members:
                    raise ValueError("no usable members")
            else:
                parsed = parse_forecast(payload, product, received_at, site)
                coverage = {"intervals": len(parsed.points)}
            status = "available"
        except (ValueError, TypeError, KeyError) as err:
            error_type = type(err).__name__
        except Exception as err:
            # Parsing can reject an HTTP-success response (units/gaps/etc.).
            error_type = type(err).__name__
    manifest = {"capture_schema": 1, "request": request, "product": product, "ensemble": ensemble,
                "software": software_provenance(),
                "collector_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "normalization_contract": "strict-member-endpoints-small-negative-dark-hour-v1",
                "response_received_at": received_at.isoformat() if raw is not None else None,
                "provider_run_at": None, "provider_run_evidence": "not_supplied_by_endpoint",
                "http_status": http_status, "status": status, "error_type": error_type,
                "field_provenance": field_provenance(product), "coverage": coverage,
                "raw_response": {"group_id": group, "sha256": digest, "byte_count": len(raw) if raw is not None else None,
                                 "event_ids": chunk_ids, "truncated": truncated}}
    batch.append(("host_weather_response", manifest, received_at, str(uuid4())))
    return journal.append_many(batch)[-1]


def reconstruct_response(event, events):
    """Resolve the exact response, reject missing/cross-source/tampered chunks."""
    reference = event["payload"]["raw_response"]
    if reference["truncated"] or reference["sha256"] is None:
        raise ValueError("original response unavailable/truncated")
    expected_bytes = reference["byte_count"]
    if type(expected_bytes) is not int or not 0 <= expected_bytes <= MAX_RESPONSE_BYTES:
        raise ValueError("response byte count exceeds bound")
    ids = reference["event_ids"]
    maximum_chunks = max(1, (MAX_RESPONSE_BYTES + CHUNK_BYTES - 1) // CHUNK_BYTES)
    if (not isinstance(ids, list) or not ids or len(ids) > maximum_chunks
            or any(not isinstance(identifier, str) or not identifier for identifier in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError("invalid response chunk references")
    selected = [item for item in events if item["event_id"] in ids and item.get("source") == event.get("source")
                and item.get("generation") == event.get("generation")]
    if len(selected) != len(ids):
        raise ValueError("missing response chunks")
    chunks, total_bytes = {}, 0
    for item in selected:
        part = item["payload"]
        index = part["index"]
        if (item["kind"] != "host_weather_response_chunk" or part["group_id"] != reference["group_id"]
                or part["response_sha256"] != reference["sha256"] or type(index) is not int
                or type(part["count"]) is not int or part["count"] != len(ids)
                or not 0 <= index < len(ids) or index in chunks or item["received_at"] != event["received_at"]):
            raise ValueError("inconsistent response chunks")
        encoded = part["base64"]
        if not isinstance(encoded, str) or len(encoded) > 4 * ((CHUNK_BYTES + 2) // 3):
            raise ValueError("response encoded chunk exceeds bound")
        decoded = base64.b64decode(encoded, validate=True)
        if len(decoded) > CHUNK_BYTES:
            raise ValueError("response decoded chunk exceeds bound")
        total_bytes += len(decoded)
        if total_bytes > expected_bytes or total_bytes > MAX_RESPONSE_BYTES:
            raise ValueError("response total exceeds declared byte bound")
        chunks[index] = decoded
    raw = b"".join(chunks[index] for index in range(len(ids)))
    if len(raw) != reference["byte_count"] or hashlib.sha256(raw).hexdigest() != reference["sha256"]:
        raise ValueError("response checksum mismatch")
    return raw


async def collect(args):
    site = SiteConfig.from_dict(json.loads(args.site_json.read_text())) if args.site_json else None
    latitude = site.latitude if site is not None else args.latitude
    longitude = site.longitude if site is not None else args.longitude
    if latitude is None or longitude is None:
        raise ValueError("provide --site-json or both coordinates")
    source = args.source
    store = ArchiveStore(args.archive)
    source_key = hashlib.sha256(source.encode()).hexdigest()[:16]
    journal = ArchiveJournal(args.archive / f"weather-staging-{source_key}", max_bytes=128 * 1024 * 1024)
    # Drain an earlier interrupted invocation before collecting new responses.
    flush_journal(journal, store, source)
    records = []
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=40)) as session:
        for ensemble, products in ((False, args.deterministic), (True, args.ensembles)):
            for product in products:
                if ensemble and product not in ENSEMBLE_COUNTS:
                    raise ValueError("unsupported ensemble product")
                params = request_params(latitude, longitude, product, args.hours)
                url = ENSEMBLE_URL if ensemble else FORECAST_URL
                request = {"url": url, "params": params, "started_at": datetime.now(UTC).isoformat()}
                raw, http_status, error, truncated = None, None, None, False
                try:
                    async with session.get(url, params=params) as response:
                        http_status = response.status
                        parts, size = [], 0
                        async for part in response.content.iter_chunked(64 * 1024):
                            size += len(part)
                            parts.append(part)
                            if size > MAX_RESPONSE_BYTES:
                                truncated = True
                                break
                        raw = b"".join(parts)
                        received = datetime.now(UTC)  # Actual end of response receipt, before parsing.
                except (aiohttp.ClientError, TimeoutError) as err:
                    received, error = datetime.now(UTC), type(err).__name__
                event = archive_response(journal, request, raw, received, product=product, ensemble=ensemble,
                                         http_status=http_status, error_type=error, site=site, truncated=truncated)
                flush_journal(journal, store, source)
                records.append({"event_id": event["event_id"], "product": product,
                                "received_at": event["received_at"], "status": event["payload"]["status"],
                                "coverage": event["payload"]["coverage"]})
    return records


def comma_list(value):
    result = tuple(item.strip() for item in value.split(",") if item.strip())
    if len(set(result)) != len(result):
        raise argparse.ArgumentTypeError("duplicate products")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--site-json", type=Path, help="Private SiteConfig JSON; supplies coordinates and night normalization")
    parser.add_argument("--latitude", type=float)
    parser.add_argument("--longitude", type=float)
    parser.add_argument("--hours", type=int, default=193)
    parser.add_argument("--deterministic", type=comma_list, default=DEFAULT_DETERMINISTIC)
    parser.add_argument("--ensembles", type=comma_list, default=DEFAULT_ENSEMBLES)
    parser.add_argument("--source", default="weather-host")
    args = parser.parse_args()
    try:
        records = asyncio.run(collect(args))
    except (ValueError, OSError) as err:
        print(f"Capture failed: {type(err).__name__}", file=sys.stderr)
        return 2
    print(json.dumps({"capture_schema": 1, "records": records}, sort_keys=True))
    return 0 if records and all(row["status"] == "available" for row in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
