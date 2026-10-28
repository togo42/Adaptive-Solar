"""Opt-in original-input journal; storage work never runs on HA's event loop."""
from __future__ import annotations

import asyncio
import base64
from collections import deque
from dataclasses import asdict, is_dataclass
from datetime import datetime
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import json
import math
from pathlib import Path
from uuid import uuid4
import zlib

CONF_ARCHIVE_EXPORT = "archive_export"
MAX_PENDING_EVENTS = 64
MAX_PENDING_BYTES = 8 * 1024 * 1024
CHUNK_BYTES = 200_000
MAX_INLINE_BYTES = 500_000


def json_value(value):
    """Portable JSON, including explicit invalid provider numbers, never pickle."""
    if is_dataclass(value):
        return json_value(asdict(value))
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_value(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return {"invalid_number": str(value)}
    return value


def encoded(value):
    return json.dumps(json_value(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def software_provenance():
    root = Path(__file__).parent
    source = sha256()
    for path in sorted(root.rglob("*.py")):
        source.update(str(path.relative_to(root)).encode())
        source.update(path.read_bytes())
    versions = {}
    for name in ("pvlib", "scikit-learn", "numpy", "scipy", "homeassistant"):
        try:
            versions[name] = version(name)
        except PackageNotFoundError:
            versions[name] = None
    return {"source_sha256": source.hexdigest(), "integration_version": json.loads((root / "manifest.json").read_text())["version"],
            "libraries": versions, "export_schema": 1}


def payload_events(kind, payload, received, event_id=None):
    """Retain an oversized source/output behind bounded compressed chunks."""
    raw = encoded(payload).encode()
    event_id = event_id or str(uuid4())
    if len(raw) <= MAX_INLINE_BYTES:
        return [(kind, payload, received, event_id)]
    if len(raw) > 128 * 1024 * 1024:
        raise ValueError("Archive payload exceeds uncompressed bound")
    digest = sha256(raw).hexdigest()
    compressed = base64.b64encode(zlib.compress(raw, level=6)).decode("ascii")
    pieces = [compressed[offset:offset + CHUNK_BYTES] for offset in range(0, len(compressed), CHUNK_BYTES)]
    group = str(uuid4())
    chunk_kind = "forecast_payload_chunk" if kind == "forecast_issued" else "weather_payload_chunk"
    events = [(chunk_kind, {"group_id": group, "payload_sha256": digest, "index": index,
                           "count": len(pieces), "encoding": "zlib+base64", "uncompressed_bytes": len(raw),
                           "data_fragment": piece}, received, str(uuid4())) for index, piece in enumerate(pieces)]
    keys = ("issued_at", "computed_at", "replay_state") if kind == "forecast_issued" else ("model", "status")
    manifest = {key: payload[key] for key in keys if key in payload}
    manifest["payload_ref"] = {"group_id": group, "sha256": digest, "encoding": "zlib+base64",
                               "uncompressed_bytes": len(raw), "event_ids": [event[3] for event in events]}
    events.append((kind, manifest, received, event_id))
    return events


def replay_events(payload, state, received):
    """Split exact fitted inputs; repeat references so TTL cannot orphan reuse."""
    text = encoded(state)
    raw = text.encode()
    if len(raw) > 128 * 1024 * 1024:
        raise ValueError("Replay state exceeds uncompressed bound")
    digest = sha256(raw).hexdigest()
    compressed = base64.b64encode(zlib.compress(raw, level=6)).decode("ascii")
    parts = [compressed[offset:offset + CHUNK_BYTES] for offset in range(0, len(compressed), CHUNK_BYTES)]
    group = str(uuid4())
    events = []
    for index, part in enumerate(parts):
        events.append(("forecast_state_chunk", {"group_id": group, "state_sha256": digest, "index": index,
                                               "count": len(parts), "encoding": "zlib+base64",
                                               "uncompressed_bytes": len(raw), "data_fragment": part}, received, str(uuid4())))
    payload = {**payload, "replay_state": {"group_id": group, "sha256": digest,
                                           "encoding": "zlib+base64", "uncompressed_bytes": len(raw),
                                           "event_ids": [event[3] for event in events]}}
    events.extend(payload_events("forecast_issued", payload, received))
    # Encoding is in the calculation worker, before taking queue ownership.
    return [(kind, encoded(data), stamp, event_id) for kind, data, stamp, event_id in events]


class ArchiveExport:
    """A bounded queue and serialized executor journal, independent of learning."""

    def __init__(self, hass, entry_id, *, enabled=False):
        self.hass = hass
        self.enabled = enabled
        self.root = hass.config.path("adaptive_solar_archive", entry_id)
        self.journal = None
        self._pending = deque()
        self._pending_bytes = 0
        self._inflight_bytes = 0
        self._inflight_events = 0
        self._worker = None
        self._active = False
        self._closed = False
        self._lock = asyncio.Lock()
        self._status = {"enabled": enabled, "state": "pending_setup" if enabled else "disabled",
                        "dropped_events": 0, "last_error": None}
        self._stats = {}
        self._state_cache = {}
        self._reported_drops = 0

    @property
    def status(self):
        return {**self._stats, **self._status,
                "dropped_events": self._stats.get("dropped_events", 0) + self._status["dropped_events"],
                "state": "gap" if self._stats.get("dropped_events", 0) and self._status["state"] == "active" else self._status["state"],
                "pending_events": len(self._pending),
                "pending_bytes": self._pending_bytes, "inflight_bytes": self._inflight_bytes,
                "inflight_events": self._inflight_events}

    def record(self, kind, payload, received, event_id=None):
        """Small source reports only; original payload is not mutated afterwards."""
        if not self.enabled or self._closed:
            return
        # Estimate without serializing on the event loop; provider responses
        # are encoded in their parser executor before this entry point.
        if not isinstance(payload, str):
            # Source reports are small and bounded; weather callers encode in
            # their existing parser worker.
            payload = encoded(payload)
        self.submit([(kind, payload, received, event_id or str(uuid4()))])

    def submit(self, events):
        if not self.enabled or self._closed:
            return
        if any(event[0] == "export_failure" for event in events):
            self._status.update(state="error", last_error="snapshot_failed")
        size = sum(len(event[1].encode()) for event in events)
        if (len(self._pending) + self._inflight_events + len(events) > MAX_PENDING_EVENTS
                or self._pending_bytes + self._inflight_bytes + size > MAX_PENDING_BYTES):
            self._status.update(state="gap", last_error="pending_overflow",
                                dropped_events=self._status["dropped_events"] + len(events))
            return
        self._pending.extend(events)
        self._pending_bytes += size
        if self._active:
            self._start_worker()

    def activate(self):
        if self.enabled and not self._closed:
            self._active = True
            if self._status["state"] == "pending_setup":
                self._status["state"] = "active" if not self._status["dropped_events"] else "gap"
            self._start_worker()

    def _start_worker(self):
        if self._worker is None or self._worker.done():
            self._worker = self.hass.async_create_task(self._drain(), "Adaptive Solar archive export")

    def _write(self, events):
        from .core.archive import ArchiveJournal

        if self.journal is None:
            self.journal = ArchiveJournal(self.root)
        stats = self.journal.stats()
        batch = []
        for kind, text, received, event_id in events:
            data = json.loads(text)
            if kind == "weather_response" and len(text) > MAX_INLINE_BYTES:
                batch.extend(payload_events(kind, data, received, event_id))
            else:
                batch.append((kind, data, received, event_id))
        drops = self._status["dropped_events"]
        if drops > self._reported_drops:
            batch.insert(0, ("export_gap", {"reason": self._status["last_error"],
                            "dropped_events_since_start": drops},
                            events[-1][2] if events else datetime.now().astimezone(), None))
        if not batch:
            return stats
        # Reserve the entire expanded batch, including weather chunks and a gap
        # marker, before deciding whether old cached references can survive it.
        budget = sum(len(encoded(data).encode()) + 512 for _, data, *_ in batch)
        headroom = (stats["event_bytes"] + budget < stats["max_bytes"]
                    and stats["events"] + len(batch) < stats["max_events"])
        newest_received = max(event[2] for event in batch)
        groups, new_chunks, pending_cache = {}, {}, {}
        # A compressed full payload already binds its original state IDs. Keep
        # those chunks; rewriting only the small manifest would orphan them.
        immutable_groups = {data["replay_state"]["group_id"]
                            for kind, data, *_ in batch if kind == "forecast_issued" and "payload_ref" in data}
        prepared = []
        for kind, data, received, event_id in batch:
            if kind == "forecast_state_chunk":
                group = data["group_id"]
                if group not in groups:
                    cached = self._state_cache.get(data["state_sha256"])
                    reuse = None
                    if (group not in immutable_groups and cached and headroom
                            and 0 <= (newest_received - cached["received"]).total_seconds() < 70 * 3600):
                        page = self.journal.page(cursor=cached["before_cursor"], limit=1)
                        if page["events"] and page["events"][0]["event_id"] == cached["reference"]["event_ids"][0]:
                            reuse = cached["reference"]
                    groups[group] = reuse
                if groups[group] is not None:
                    continue
                new_chunks.setdefault(group, []).append(event_id)
            if kind == "forecast_issued":
                ref = data["replay_state"]
                group = ref["group_id"]
                if groups.get(group) is not None:
                    data["replay_state"] = groups[group]
                elif group in new_chunks:
                    pending_cache[ref["sha256"]] = {
                        "reference": ref, "received": received, "first_id": new_chunks[group][0],
                    }
            prepared.append((kind, data, received, event_id))
        committed = self.journal.append_many(prepared)
        # Neither a failed append nor its provisional sequence estimates may
        # enter the reuse cache. Publish references only after the whole commit.
        by_id = {event["event_id"]: event for event in committed}
        for digest, cached in pending_cache.items():
            first = by_id[cached.pop("first_id")]
            cached["before_cursor"] = f'{first["generation"]}:{first["sequence"] - 1}'
            self._state_cache[digest] = cached
            if len(self._state_cache) > 32:
                del self._state_cache[next(iter(self._state_cache))]
        self._reported_drops = drops
        return self.journal.stats()

    async def _drain(self):
        async with self._lock:
            while self._pending:
                events = list(self._pending)
                self._pending.clear()
                self._inflight_bytes = self._pending_bytes
                self._inflight_events = len(events)
                self._pending_bytes = 0
                try:
                    self._stats = await self.hass.async_add_executor_job(self._write, events)
                except Exception as err:
                    # No exception text: provider/config paths can be private.
                    self._status.update(state="error", last_error=type(err).__name__,
                                        dropped_events=self._status["dropped_events"] + len(events))
                finally:
                    self._inflight_bytes = self._inflight_events = 0

    async def page(self, cursor=None, limit=100, max_bytes=2 * 1024 * 1024):
        if not self.enabled:
            return {"page": None, "status": self.status}
        if self._worker is not None:
            await self._worker
        async with self._lock:
            def read():
                if self.journal is None:
                    self._write([])
                return self.journal.page(cursor=cursor, limit=limit, max_bytes=max_bytes)
            try:
                result = await self.hass.async_add_executor_job(read)
            except ValueError:
                raise
            except Exception as err:
                self._status.update(state="error", last_error=type(err).__name__)
                result = None
        return {"page": result, "status": self.status}

    async def close(self):
        self._closed = True
        if self._active:
            if self._worker is not None:
                await self._worker
        else:
            self._pending.clear()
            self._pending_bytes = 0
