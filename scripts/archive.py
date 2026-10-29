#!/usr/bin/env python3
"""Read-only HA export collection and explicit local archive maintenance."""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlsplit, urlunsplit

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from custom_components.adaptive_solar.core.archive import (  # noqa: E402
    MAX_PAGE_BYTES, ArchiveError, ArchiveStore, validate_page,
)

PRODUCER_STATES = {"active", "gap", "error", "disabled", "pending_setup", "unknown"}
COLLECTION_FAILURES = {"producer_error", "producer_pending", "page_unavailable", "cursor_gap", "incomplete_collection"}


def producer_status(value, *, raw=True):
    """Only fixed enums, booleans and counts may leave the producer boundary."""
    value = value if isinstance(value, dict) else {}
    state = value.get("state")
    error = ("last_error" not in value or value["last_error"] is not None) if raw else (
        type(value.get("error")) is not bool or value["error"])
    result = {"state": state if isinstance(state, str) and state in PRODUCER_STATES else "unknown",
              "enabled": value.get("enabled") is True, "error": error}
    for key in ("dropped_events", "pending_events", "inflight_events"):
        number = value.get(key)
        result[key] = number if type(number) is int and number >= 0 else None
    return result


def producer_healthy(value):
    return (value["enabled"] and value["state"] in {"active", "gap"} and not value["error"]
            and all(value[key] is not None for key in ("dropped_events", "pending_events", "inflight_events")))


def collection_summary(value):
    """Independently verify completion and remove cursors, source IDs and raw text."""
    if (not isinstance(value, dict) or any(type(value.get(key)) is not bool for key in (
            "complete", "collection_end_confirmed", "page_limit_reached"))
            or any(type(value.get(key)) is not int or value[key] < 0 for key in ("pages", "events"))
            or not isinstance(value.get("gaps"), list) or not isinstance(value.get("failures"), list)
            or any(not isinstance(reason, str) or reason not in COLLECTION_FAILURES for reason in value["failures"])):
        raise ArchiveError("Invalid collector completion status")
    producer = producer_status(value.get("producer"), raw=False)
    complete = (value["complete"] and value["collection_end_confirmed"] and not value["page_limit_reached"]
                and not value["gaps"] and not value["failures"] and producer_healthy(producer)
                and producer["pending_events"] == producer["inflight_events"] == 0)
    return {"complete": complete, "pages": value["pages"], "events": value["events"],
            "gap_count": len(value["gaps"]), "end_confirmed": value["collection_end_confirmed"],
            "page_limit_reached": value["page_limit_reached"], "failures": sorted(set(value["failures"])),
            "producer": producer}


def websocket_url(value):
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https", "ws", "wss"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError
        _ = parsed.port
        path = parsed.path.rstrip("/")
        if not path.endswith("/api/websocket"):
            path += "/api/websocket"
        return urlunsplit(("wss" if parsed.scheme in {"https", "wss"} else "ws", parsed.netloc, path, "", ""))
    except (ValueError, AttributeError) as exc:
        raise ArchiveError("HA_URL must be a base URL without credentials or query") from exc


async def fetch_page(ha_url, token, entry_id, cursor, *, limit=100, max_bytes=2 * 1024 * 1024,
                     timeout=30, session=None):
    """Invoke only the authenticated archive export service; no provider refresh."""
    url = websocket_url(ha_url)
    if not isinstance(token, str) or not token.strip():
        raise ArchiveError("HA_TOKEN is required")
    if not isinstance(entry_id, str) or not entry_id.strip():
        raise ArchiveError("An explicit config entry is required")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 120:
        raise ArchiveError("Timeout must be between zero and 120 seconds")

    async def request(client):
        async with asyncio.timeout(timeout):
            async with client.ws_connect(url, max_msg_size=MAX_PAGE_BYTES + 65536) as ws:
                first = await ws.receive_json()
                if not isinstance(first, dict) or first.get("type") != "auth_required":
                    raise ArchiveError("Unexpected HA authentication handshake")
                await ws.send_json({"type": "auth", "access_token": token})
                authenticated = await ws.receive_json()
                if not isinstance(authenticated, dict) or authenticated.get("type") != "auth_ok":
                    raise ArchiveError("HA authentication failed")
                service_data = {"config_entry_id": entry_id, "limit": limit, "max_bytes": max_bytes}
                if cursor is not None:
                    service_data["cursor"] = cursor
                await ws.send_json(dict(id=1, type="call_service", domain="adaptive_solar",
                                        service="export_archive", service_data=service_data, return_response=True))
                result = await ws.receive_json()
                if (not isinstance(result, dict) or result.get("type") != "result"
                        or type(result.get("id")) is not int or result["id"] != 1
                        or result.get("success") is not True):
                    raise ArchiveError("HA archive export failed")
                body = result.get("result")
                response = body.get("response") if isinstance(body, dict) else None
                page = response.get("page") if isinstance(response, dict) else None
                if page is not None:
                    validate_page(page)
                if page is not None and page["requested_cursor"] != cursor:
                    raise ArchiveError("Export page does not match requested cursor")
                return {"page": page, "producer": producer_status(response.get("status") if isinstance(response, dict) else None)}
    if session is not None:
        return await request(session)
    async with aiohttp.ClientSession() as client:
        return await request(client)


async def collect(store, source, fetch, *, max_pages=100):
    """Fetch until empty/no progress, committing each durable page before the next."""
    if type(max_pages) is not int or not 1 <= max_pages <= 10000:
        raise ArchiveError("max_pages must be between one and 10000")
    cursor = await asyncio.to_thread(store.checkpoint, source)
    pages = events = 0
    gaps = []
    failures = set()
    producer = producer_status(None)
    confirmed = page_limit = False
    for _ in range(max_pages):
        fetched = await fetch(cursor)
        if isinstance(fetched, dict) and "page" in fetched:
            page = fetched["page"]
            producer = producer_status(fetched.get("producer"), raw=False)
        else:
            page, producer = fetched, producer_status(None)
        if not producer_healthy(producer):
            failures.add("producer_error")
        if page is None:
            failures.add("page_unavailable")
            break
        validate_page(page)
        if page["requested_cursor"] != cursor:
            raise ArchiveError("Collector page cursor mismatch")
        new_cursor = await asyncio.to_thread(store.ingest_page, source, page)
        pages += 1
        events += len(page["events"])
        if page["gap"]:
            gaps.append(page["gap"])
        if new_cursor == cursor or not page["events"]:
            cursor = new_cursor
            confirmed = not page["events"]
            break
        cursor = new_cursor
    else:
        page_limit = True
    if gaps:
        failures.add("cursor_gap")
    if not confirmed:
        failures.add("incomplete_collection")
    if producer["pending_events"] != 0 or producer["inflight_events"] != 0:
        failures.add("producer_pending")
    return dict(pages=pages, events=events, gaps=gaps, cursor=cursor, producer=producer,
                collection_end_confirmed=confirmed, failures=sorted(failures), complete=not failures,
                page_limit_reached=page_limit)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="Private local archive directory")
    commands = parser.add_subparsers(dest="command", required=True)
    observations = commands.add_parser("export-observations", help="Export exact captured revisions as evaluation JSONL")
    observations.add_argument("--source", required=True)
    observations.add_argument("--kind", choices=("actuals", "references"), required=True)
    observations.add_argument("--dataset")
    observations.add_argument("--output", type=Path, required=True)
    capture = commands.add_parser("collect", help="Read HA export using HA_URL and HA_TOKEN")
    capture.add_argument("--source", required=True, help="Stable private producer identity")
    capture.add_argument("--entry-id", required=True)
    capture.add_argument("--max-pages", type=int, default=100)
    capture.add_argument("--limit", type=int, default=100)
    capture.add_argument("--max-bytes", type=int, default=2 * 1024 * 1024)
    commands.add_parser("stats", help="Capacity and three/six month review checkpoints")
    commands.add_parser("verify", help="Read and verify all originals")
    commands.add_parser("rebuild-index", help="Explicitly reconstruct derived index from verified originals")
    commands.add_parser("maintain", help="Apply 24 calendar month retention, preserving pins")
    migration = commands.add_parser("migrate-layout", help="Relocate verified originals without changing hashes or pins")
    migration.add_argument("--layout", choices=("hash-prefix", "flat"), default="hash-prefix")
    export = commands.add_parser("export-dataset", help="Copy frozen originals and an immutable manifest")
    export.add_argument("dataset")
    export.add_argument("destination", type=Path)
    export.add_argument("--layout", choices=("hash-prefix", "flat"), default="hash-prefix",
                        help="Use flat for replay with older software")
    pin = commands.add_parser("pin", help="Permanently pin a named immutable dataset")
    pin.add_argument("dataset")
    pin.add_argument("--source", action="append")
    args = parser.parse_args(argv)
    try:
        # An explicit rebuild must also work when the existing index is corrupt/unknown.
        if args.command == "rebuild-index":
            store = ArchiveStore.__new__(ArchiveStore)
            store.root, store.originals = args.root, args.root / "originals"
            if not store.originals.is_dir():
                raise ArchiveError("No originals directory to rebuild")
            store.rebuild_index()
            result = {"rebuilt": True}
        else:
            store = ArchiveStore(args.root)
            if args.command == "collect":
                async def fetch(cursor):
                    return await fetch_page(os.environ.get("HA_URL", ""), os.environ.get("HA_TOKEN", ""),
                                            args.entry_id, cursor, limit=args.limit, max_bytes=args.max_bytes)
                result = asyncio.run(collect(store, args.source, fetch, max_pages=args.max_pages))
            elif args.command == "export-observations":
                from scripts.archive_observations import captures_from_archive
                if args.output.exists():
                    raise ArchiveError("Observation output already exists")
                fd, temporary = tempfile.mkstemp(prefix=".observation-export-", dir=args.output.parent)
                try:
                    count = 0
                    with os.fdopen(fd, "w", encoding="utf-8") as handle:
                        for capture in captures_from_archive(store, source=args.source, kind=args.kind, dataset=args.dataset):
                            handle.write(json.dumps(capture, ensure_ascii=False, allow_nan=False) + "\n")
                            count += 1
                        handle.flush()
                        os.fsync(handle.fileno())
                    # Hard link publishes atomically and fails if the output already exists.
                    os.link(temporary, args.output)
                    directory = os.open(args.output.parent, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
                    result = {"captures": count}
                finally:
                    Path(temporary).unlink(missing_ok=True)
            elif args.command == "stats":
                result = store.stats()
            elif args.command == "verify":
                result = {"verified": store.verify()}
            elif args.command == "maintain":
                result = store.maintain()
            elif args.command == "migrate-layout":
                result = store.migrate_layout(layout=args.layout)
            elif args.command == "export-dataset":
                result = store.export_dataset(args.dataset, args.destination, layout=args.layout)
            else:
                result = {"pinned": store.pin(args.dataset, sources=args.source)}
        print(json.dumps(result, sort_keys=True))
        return 1 if args.command == "collect" and not result["complete"] else 0
    except (ArchiveError, OSError, TimeoutError, aiohttp.ClientError):
        # Upstream exception strings can contain URLs, tokens or private payloads.
        print("Archive operation failed; checkpoint retained. Check private local diagnostics.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
