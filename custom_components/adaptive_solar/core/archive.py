"""Bounded export journal and host originals archive (no Home Assistant imports).

All methods perform blocking I/O and must run in an executor in async callers.
Checksums prove byte integrity, not the authenticity of the claimed producer.
"""
from __future__ import annotations

from calendar import monthrange
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import uuid
import zlib

SCHEMA = 1
MAX_EVENT_BYTES = 1024 * 1024
MAX_PAGE_BYTES = 4 * 1024 * 1024
MAX_PAGE_EVENTS = 1000


class ArchiveError(ValueError):
    """Invalid archive data or an operation that cannot be completed safely."""


def canonical_bytes(value) -> bytes:
    def check_keys(item):
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ArchiveError("Archive JSON object keys must be strings")
            for nested in item.values():
                check_keys(nested)
        elif isinstance(item, (list, tuple)):
            for nested in item:
                check_keys(nested)
    try:
        check_keys(value)
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False).encode("utf-8")
    except ArchiveError:
        raise
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ArchiveError("Archive data must be finite JSON") from exc


def _stamp(value) -> datetime:
    try:
        stamp = datetime.fromisoformat(value) if isinstance(value, str) else value
        if not isinstance(stamp, datetime) or stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError
        return stamp.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ArchiveError("Archive timestamp must be timezone aware") from exc


def _text(value, name, maximum=256):
    if not isinstance(value, str) or not value or len(value) > maximum or value != value.strip():
        raise ArchiveError(f"Invalid archive {name}")
    return value


def _int(value, name, low=0, high=2**63 - 1):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ArchiveError(f"Invalid archive {name}")
    return value


def _generation(value):
    try:
        if not isinstance(value, str) or str(uuid.UUID(value)) != value:
            raise ValueError
    except (ValueError, AttributeError) as exc:
        raise ArchiveError("Invalid archive generation") from exc
    return value


def parse_cursor(cursor):
    if cursor is None:
        return None
    try:
        gen, seq = cursor.split(":")
        if not seq.isdecimal():
            raise ValueError
        return _generation(gen), _int(int(seq), "cursor sequence")
    except (ValueError, AttributeError) as exc:
        raise ArchiveError("Invalid archive cursor") from exc


def validate_envelope(event):
    if not isinstance(event, dict) or set(event) != {
            "schema", "generation", "sequence", "event_id", "kind", "received_at", "payload", "sha256"}:
        raise ArchiveError("Malformed archive envelope")
    if type(event["schema"]) is not int or event["schema"] != SCHEMA:
        raise ArchiveError("Unknown archive envelope schema")
    _generation(event["generation"])
    _int(event["sequence"], "sequence", 1)
    _text(event["event_id"], "event ID")
    _text(event["kind"], "kind", 128)
    _stamp(event["received_at"])
    if not isinstance(event["payload"], dict):
        raise ArchiveError("Archive payload must be an object")
    raw = canonical_bytes({k: v for k, v in event.items() if k != "sha256"})
    if event["sha256"] != hashlib.sha256(raw).hexdigest():
        raise ArchiveError("Archive envelope checksum mismatch")
    if len(canonical_bytes(event)) > MAX_EVENT_BYTES:
        raise ArchiveError("Archive event exceeds hard byte limit")
    return event


def validate_page(page):
    if not isinstance(page, dict) or set(page) != {
            "schema", "generation", "oldest_sequence", "requested_cursor", "next_cursor", "events", "gap"}:
        raise ArchiveError("Malformed archive page")
    if type(page["schema"]) is not int or page["schema"] != SCHEMA:
        raise ArchiveError("Unknown archive page schema")
    gen = _generation(page["generation"])
    oldest = _int(page["oldest_sequence"], "oldest sequence", 1)
    request = parse_cursor(page["requested_cursor"])
    nxt = parse_cursor(page["next_cursor"])
    if nxt is None or nxt[0] != gen or not isinstance(page["events"], list):
        raise ArchiveError("Malformed page cursor/events")
    if len(page["events"]) > MAX_PAGE_EVENTS or len(canonical_bytes(page)) > MAX_PAGE_BYTES:
        raise ArchiveError("Archive page exceeds hard limits")
    gap = page["gap"]
    if gap is not None:
        if not isinstance(gap, dict) or set(gap) != {"reason", "from", "to"}:
            raise ArchiveError("Malformed archive gap")
        if gap["reason"] not in {"retention_or_overflow", "generation_changed"}:
            raise ArchiveError("Unknown archive gap reason")
        _int(gap["from"], "gap start")
        _int(gap["to"], "gap end")
    start = request[1] if request and request[0] == gen else 0
    expected_gap = ("generation_changed" if request and request[0] != gen
                    else "retention_or_overflow" if start < oldest - 1 else None)
    if (gap is None) != (expected_gap is None) or (gap and gap["reason"] != expected_gap):
        raise ArchiveError("Page must explicitly describe cursor discontinuity")
    if gap and (gap["from"] != start + 1 or gap["to"] != oldest - 1):
        raise ArchiveError("Archive gap range mismatch")
    previous = max(start, oldest - 1)
    for event in page["events"]:
        validate_envelope(event)
        if event["generation"] != gen or event["sequence"] != previous + 1:
            raise ArchiveError("Archive page sequence discontinuity")
        previous = event["sequence"]
    if nxt[1] != previous:
        raise ArchiveError("Archive next cursor does not match events")
    return page


@contextmanager
def _lock(root):
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / ".archive.lock").open("a+b") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def _fsync_dir(root):
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic(root, name, raw):
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=root)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, root / name)
        _fsync_dir(root)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class _Connection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def _connect(path, kind, *, check_integrity=False):
    exists = path.exists()
    try:
        conn = sqlite3.connect(path, timeout=30, factory=_Connection)
        conn.execute("PRAGMA synchronous=FULL")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if exists and version != SCHEMA:
            conn.close()
            raise ArchiveError("Unknown archive index schema; original preserved")
        if exists and check_integrity and conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            conn.close()
            raise ArchiveError("Corrupt archive index; original preserved")
        if not exists:
            conn.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        prior = conn.execute("SELECT value FROM metadata WHERE key='kind'").fetchone()
        if prior and prior[0] != kind:
            conn.close()
            raise ArchiveError("Wrong archive index kind")
        if exists and not prior:
            conn.close()
            raise ArchiveError("Unrecognized archive index; original preserved")
        if exists:
            required = {"events"} if kind == "journal" else {"batches", "events", "checkpoints"}
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not required <= tables:
                conn.close()
                raise ArchiveError("Incomplete archive index schema; original preserved")
            expected = {"metadata": {"key", "value"}}
            if kind == "journal":
                expected["events"] = {"sequence", "event_id", "received_at", "raw"}
            else:
                expected.update(batches={"hash", "source", "ingest_order", "stored_at", "bytes"},
                                events={"source", "generation", "sequence", "event_id", "sha256", "batch"},
                                checkpoints={"source", "cursor", "ingest_order"})
            for table, columns in expected.items():
                if {row[1] for row in conn.execute(f"PRAGMA table_info({table})")} != columns:
                    conn.close()
                    raise ArchiveError("Unexpected archive index columns; original preserved")
        if not exists:
            conn.execute(f"PRAGMA user_version={SCHEMA}")
            conn.execute("INSERT INTO metadata VALUES('kind',?)", (kind,))
        return conn
    except sqlite3.Error as exc:
        if "conn" in locals():
            conn.close()
        raise ArchiveError("Archive index unavailable or corrupt") from exc


class ArchiveJournal:
    """Short-lived durable HA export buffer; bounds refer to serialized event bytes."""

    def __init__(self, root, *, max_bytes=64 * 1024 * 1024, max_events=10000,
                 retention_hours=72, max_event_bytes=MAX_EVENT_BYTES):
        self.root = Path(root)
        self.max_bytes = _int(max_bytes, "byte bound", 1024)
        self.max_events = _int(max_events, "event bound", 1)
        self.retention_hours = _int(retention_hours, "retention hours", 1)
        self.max_event_bytes = _int(max_event_bytes, "event byte bound", 512, min(MAX_EVENT_BYTES, max_bytes))
        self.physical_limit_bytes = 2 * self.max_bytes + 8 * 1024 * 1024
        with _lock(self.root):
            fresh = not (self.root / "journal.sqlite3").exists()
            # Existing bytes are validated before metadata writes or compaction.
            with _connect(self.root / "journal.sqlite3", "journal", check_integrity=True) as conn:
                if fresh:
                    conn.execute("CREATE TABLE events(sequence INTEGER PRIMARY KEY,event_id TEXT UNIQUE,received_at TEXT,raw BLOB)")
                    for key, value in (("generation", str(uuid.uuid4())), ("next_sequence", "1"), ("dropped_events", "0")):
                        conn.execute("INSERT INTO metadata VALUES(?,?)", (key, value))
                self._validate_state(conn)
            with self._db(compact=True):
                pass
            _fsync_dir(self.root)

    @staticmethod
    def _validate_state(conn):
        meta = dict(conn.execute("SELECT key,value FROM metadata"))
        if not {"generation", "next_sequence", "dropped_events"} <= meta.keys():
            raise ArchiveError("Incomplete journal metadata; original preserved")
        generation = _generation(meta["generation"])
        counters = {}
        for key, minimum in (("next_sequence", 1), ("dropped_events", 0)):
            value = meta[key]
            if not isinstance(value, str) or not 1 <= len(value) <= 19 or not value.isdecimal():
                raise ArchiveError("Malformed journal metadata; original preserved")
            counters[key] = _int(int(value), key, minimum)
        count, previous = 0, None
        for sequence, identifier, received, raw in conn.execute(
                "SELECT sequence,event_id,received_at,raw FROM events ORDER BY sequence"):
            try:
                event = validate_envelope(json.loads(raw))
            except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
                raise ArchiveError("Corrupt journal event; original preserved") from exc
            if (event["generation"] != generation or event["sequence"] != sequence
                    or event["event_id"] != identifier or event["received_at"] != received
                    or (previous is not None and sequence != previous + 1)):
                raise ArchiveError("Inconsistent journal event metadata; original preserved")
            previous = sequence
            count += 1
        if ((previous is not None and previous + 1 != counters["next_sequence"])
                or counters["dropped_events"] != counters["next_sequence"] - 1 - count):
            raise ArchiveError("Inconsistent journal sequence counters; original preserved")

    def _db(self, *, check_integrity=False, compact=False):
        conn = _connect(self.root / "journal.sqlite3", "journal", check_integrity=check_integrity)
        try:
            page_size = conn.execute("PRAGMA page_size").fetchone()[0]
            page_limit = min(self.physical_limit_bytes // page_size, 4294967294)
            current_pages = conn.execute("PRAGMA page_count").fetchone()[0]
            if current_pages > page_limit and compact:
                # At most once when reopening with a smaller configured bound.
                conn.execute("VACUUM")
            actual_limit = conn.execute(f"PRAGMA max_page_count={page_limit}").fetchone()[0]
            if actual_limit > page_limit:
                raise ArchiveError("Journal physical size exceeds configured capacity")
            return conn
        except (ArchiveError, sqlite3.Error):
            conn.close()
            raise

    def append(self, kind, payload, received_at, event_id=None):
        return self.append_many([(kind, payload, received_at, event_id)])[0]

    def append_many(self, events):
        """Atomically append a whole bounded producer batch, including its manifest.

        Each item is (kind, payload, aware_received_at, event_id_or_none). A retry
        must contain only known IDs or only new IDs, never a partially known batch.
        """
        if not isinstance(events, (list, tuple)) or not 1 <= len(events) <= self.max_events:
            raise ArchiveError("Archive batch must fit the event bound")
        normalized = []
        identifiers = set()
        for item in events:
            if not isinstance(item, (list, tuple)) or len(item) != 4:
                raise ArchiveError("Archive batch items require kind, payload, timestamp and ID")
            kind, payload, received_at, event_id = item
            _text(kind, "kind", 128)
            if not isinstance(payload, dict):
                raise ArchiveError("Archive payload must be an object")
            received = _stamp(received_at).isoformat()
            identifier = _text(str(uuid.uuid4()) if event_id is None else event_id, "event ID")
            if identifier in identifiers:
                raise ArchiveError("Archive batch event IDs must be unique")
            identifiers.add(identifier)
            normalized.append((kind, payload, received, identifier))
        with _lock(self.root), self._db() as conn:
            meta = dict(conn.execute("SELECT key,value FROM metadata"))
            sequence = int(meta["next_sequence"])
            prepared, known, total_bytes = [], [], 0
            for kind, payload, received, identifier in normalized:
                prior = conn.execute("SELECT raw FROM events WHERE event_id=?", (identifier,)).fetchone()
                if prior:
                    old = validate_envelope(json.loads(prior[0]))
                    if (old["kind"] != kind or canonical_bytes(old["payload"]) != canonical_bytes(payload)
                            or old["received_at"] != received):
                        raise ArchiveError("Event ID already names different content")
                    known.append(old)
                    continue
                event = dict(schema=SCHEMA, generation=meta["generation"], sequence=sequence + len(prepared),
                             event_id=identifier, kind=kind, received_at=received, payload=payload)
                event["sha256"] = hashlib.sha256(canonical_bytes(event)).hexdigest()
                raw = canonical_bytes(event)
                if len(raw) > self.max_event_bytes:
                    raise ArchiveError("Archive event too large; producer must use bounded chunks")
                total_bytes += len(raw)
                if total_bytes > self.max_bytes:
                    raise ArchiveError("Archive batch exceeds journal byte bound")
                prepared.append((event, raw))
            if known:
                if prepared:
                    raise ArchiveError("Archive batch retry is partially known; refusing partial publication")
                return known
            _int(sequence + len(prepared), "next sequence", 1)
            # Validate the whole batch before mutations. Prune old rows before
            # allocation, reusing free pages while retaining this complete batch.
            cutoff = (_stamp(max(item[2] for item in normalized)) - timedelta(hours=self.retention_hours)).isoformat()
            newest_expired = conn.execute("SELECT max(sequence) FROM events WHERE received_at<?", (cutoff,)).fetchone()[0]
            dropped = 0
            if newest_expired:
                dropped += conn.execute("DELETE FROM events WHERE sequence<=?", (newest_expired,)).rowcount
            rows, size = conn.execute("SELECT count(*),coalesce(sum(length(raw)),0) FROM events").fetchone()
            while rows + len(prepared) > self.max_events or size + total_bytes > self.max_bytes:
                seq, length = conn.execute("SELECT sequence,length(raw) FROM events ORDER BY sequence LIMIT 1").fetchone()
                conn.execute("DELETE FROM events WHERE sequence=?", (seq,))
                rows -= 1
                size -= length
                dropped += 1
            for event, raw in prepared:
                conn.execute("INSERT INTO events VALUES(?,?,?,?)",
                             (event["sequence"], event["event_id"], event["received_at"], raw))
            conn.execute("UPDATE metadata SET value=? WHERE key='next_sequence'", (str(sequence + len(prepared)),))
            conn.execute("UPDATE metadata SET value=? WHERE key='dropped_events'", (str(int(meta["dropped_events"]) + dropped),))
            return [event for event, _ in prepared]

    def page(self, cursor=None, *, limit=100, max_bytes=2 * 1024 * 1024):
        _int(limit, "page limit", 1, MAX_PAGE_EVENTS)
        _int(max_bytes, "page byte bound", 512, MAX_PAGE_BYTES)
        parsed = parse_cursor(cursor)
        with _lock(self.root), self._db() as conn:
            meta = dict(conn.execute("SELECT key,value FROM metadata"))
            gen, tail = meta["generation"], int(meta["next_sequence"]) - 1
            oldest = conn.execute("SELECT min(sequence) FROM events").fetchone()[0] or tail + 1
            start = parsed[1] if parsed and parsed[0] == gen else 0
            if start > tail:
                raise ArchiveError("Cursor is ahead of archive journal")
            gap = None
            if parsed and parsed[0] != gen:
                gap = dict(reason="generation_changed", **{"from": 1, "to": oldest - 1})
            elif start < oldest - 1:
                gap = dict(reason="retention_or_overflow", **{"from": start + 1, "to": oldest - 1})
            position = max(start, oldest - 1)
            page = dict(schema=SCHEMA, generation=gen, oldest_sequence=oldest, requested_cursor=cursor,
                        next_cursor=f"{gen}:{position}", events=[], gap=gap)
            for seq, raw in conn.execute("SELECT sequence,raw FROM events WHERE sequence>? ORDER BY sequence LIMIT ?", (position, limit)):
                event = validate_envelope(json.loads(raw))
                candidate = {**page, "events": [*page["events"], event], "next_cursor": f"{gen}:{seq}"}
                if len(canonical_bytes(candidate)) > max_bytes:
                    if not page["events"]:
                        raise ArchiveError("Page byte bound cannot fit next event; increase max_bytes")
                    break
                page = candidate
            return validate_page(page)

    def stats(self):
        with _lock(self.root), self._db() as conn:
            meta = dict(conn.execute("SELECT key,value FROM metadata"))
            rows, size = conn.execute("SELECT count(*),coalesce(sum(length(raw)),0) FROM events").fetchone()
            return dict(schema=SCHEMA, generation=meta["generation"], events=rows, event_bytes=size,
                        dropped_events=int(meta["dropped_events"]), next_sequence=int(meta["next_sequence"]),
                        max_bytes=self.max_bytes, max_events=self.max_events, retention_hours=self.retention_hours,
                        disk_bytes=(self.root / "journal.sqlite3").stat().st_size,
                        physical_limit_bytes=self.physical_limit_bytes,
                        freelist_bytes=conn.execute("PRAGMA freelist_count").fetchone()[0]
                        * conn.execute("PRAGMA page_size").fetchone()[0],
                        transient_disk_budget_bytes=2 * self.physical_limit_bytes + 65536)

    def verify(self):
        """Explicit full SQLite and envelope integrity check, outside append hot paths."""
        with _lock(self.root), self._db(check_integrity=True) as conn:
            self._validate_state(conn)
        return True


def _months_before(stamp, months):
    index = stamp.year * 12 + stamp.month - 1 - months
    year, month = divmod(index, 12)
    return stamp.replace(year=year, month=month + 1, day=min(stamp.day, monthrange(year, month + 1)[1]))


class ArchiveStore:
    """Host archive: immutable compressed originals, disposable SQLite lookup index."""

    def __init__(self, root):
        self.root = Path(root)
        self.originals = self.root / "originals"
        with _lock(self.root):
            self.originals.mkdir(mode=0o700, exist_ok=True)
            self._validate_pins()
            with self._db(check_integrity=True) as conn:
                self._tables(conn)
            # Recover durable originals from a crash before the index commit.
            self._reconcile()

    def _db(self, path=None, *, check_integrity=False):
        return _connect(path or self.root / "index.sqlite3", "host", check_integrity=check_integrity)

    @staticmethod
    def _tables(conn):
        conn.execute("CREATE TABLE IF NOT EXISTS batches(hash TEXT PRIMARY KEY,source TEXT,ingest_order INTEGER,stored_at TEXT,bytes INTEGER)")
        conn.execute("CREATE TABLE IF NOT EXISTS events(source TEXT,generation TEXT,sequence INTEGER,event_id TEXT,sha256 TEXT,batch TEXT,PRIMARY KEY(source,generation,sequence))")
        conn.execute("CREATE TABLE IF NOT EXISTS checkpoints(source TEXT PRIMARY KEY,cursor TEXT,ingest_order INTEGER)")
        conn.execute("CREATE INDEX IF NOT EXISTS events_reference ON events(source,generation,event_id)")

    def _layout_path(self, digest, layout="hash-prefix"):
        if (not isinstance(digest, str) or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)):
            raise ArchiveError("Invalid original hash")
        if layout not in {"hash-prefix", "flat"}:
            raise ArchiveError("Unknown original layout")
        parent = self.originals / digest[:2] if layout == "hash-prefix" else self.originals
        if parent.is_symlink() or self.originals.is_symlink():
            raise ArchiveError("Original directories must not be symlinks")
        return parent / f"{digest}.json.gz"

    def _original_path(self, digest):
        """Resolve new and legacy originals without changing their contents."""
        path = self._layout_path(digest)
        return path if path.exists() else self._layout_path(digest, "flat")

    def _original_files(self):
        """Scan exactly the supported layouts, including interrupted migrations."""
        if self.originals.is_symlink():
            raise ArchiveError("Original directories must not be symlinks")
        for path in self.originals.glob("*.json.gz"):
            digest = path.name.removesuffix(".json.gz")
            self._layout_path(digest, "flat")
            if path.is_symlink():
                raise ArchiveError("Original must not be a symlink")
            yield path
        for directory in self.originals.iterdir():
            if directory.is_symlink():
                raise ArchiveError("Original must not be a symlink")
            if not directory.is_dir():
                continue
            if len(directory.name) != 2 or any(char not in "0123456789abcdef" for char in directory.name):
                raise ArchiveError("Unknown original directory")
            for path in directory.iterdir():
                if path.is_symlink() or path.is_dir():
                    raise ArchiveError("Unsupported original path")
                if path.name.endswith(".json.gz"):
                    digest = path.name.removesuffix(".json.gz")
                    if path != self._layout_path(digest):
                        raise ArchiveError("Original hash prefix mismatch")
                    yield path

    def _prepare_parent(self, path):
        if not path.parent.exists():
            path.parent.mkdir(mode=0o700)
            _fsync_dir(self.originals)

    def _write_original(self, digest, raw, *, layout="hash-prefix"):
        path = self._layout_path(digest, layout)
        self._prepare_parent(path)
        _atomic(path.parent, path.name, raw)

    def migrate_layout(self, *, layout="hash-prefix"):
        """Relocate verified bytes under the archive lock; resumable in either direction."""
        self._layout_path("0" * 64, layout)  # Validate before making any changes.
        with _lock(self.root):
            self._validate_pins()
            paths = list(self._original_files())
            # Validate the entire set before moving even one original.
            for path in paths:
                self._read_original(path)
                target = self._layout_path(path.name.removesuffix(".json.gz"), layout)
                if target != path and target.exists() and target.read_bytes() != path.read_bytes():
                    raise ArchiveError("Conflicting original layout copies")
            self._reconcile()
            moved = duplicates = 0
            for path in paths:
                target = self._layout_path(path.name.removesuffix(".json.gz"), layout)
                if target == path:
                    continue
                self._prepare_parent(target)
                if not target.exists():
                    # Publish without overwriting. Until destination fsync succeeds,
                    # the old name remains the durable recovery path.
                    os.link(path, target)
                    moved += 1
                else:
                    duplicates += 1
                _fsync_dir(target.parent)
                path.unlink()
                _fsync_dir(path.parent)
            return dict(layout=layout, moved_originals=moved, removed_duplicates=duplicates)

    def _read_original(self, path):
        if path.is_symlink() or path.parent.is_symlink():
            raise ArchiveError("Original must not be a symlink")
        if path.stat().st_size > MAX_PAGE_BYTES + 65536:
            raise ArchiveError("Compressed original exceeds byte bound")
        try:
            with gzip.open(path, "rb") as handle:
                raw = handle.read(MAX_PAGE_BYTES + 65537)
            if len(raw) > MAX_PAGE_BYTES + 65536:
                raise ArchiveError("Decompressed original exceeds byte bound")
            if hashlib.sha256(raw).hexdigest() != path.name.removesuffix(".json.gz"):
                raise ArchiveError("Original file checksum mismatch")
            value = json.loads(raw)
            if not isinstance(value, dict) or set(value) != {"schema", "source", "ingest_order", "stored_at", "archive_started_at", "page"}:
                raise ArchiveError("Malformed original wrapper")
            if type(value["schema"]) is not int or value["schema"] != SCHEMA:
                raise ArchiveError("Unknown original wrapper schema")
            _text(value["source"], "source")
            _int(value["ingest_order"], "ingest order", 1)
            _stamp(value["stored_at"])
            _stamp(value["archive_started_at"])
            validate_page(value["page"])
            return value
        except (OSError, EOFError, json.JSONDecodeError, UnicodeError, RecursionError, zlib.error) as exc:
            raise ArchiveError("Original file corrupt or unreadable") from exc

    @staticmethod
    def _index(conn, digest, value, size):
        source, page, order = value["source"], value["page"], value["ingest_order"]
        first = conn.execute("SELECT value FROM metadata WHERE key='archive_started_at'").fetchone()
        if not first or _stamp(value["archive_started_at"]) < _stamp(first[0]):
            conn.execute("INSERT OR REPLACE INTO metadata VALUES('archive_started_at',?)", (value["archive_started_at"],))
        if conn.execute("SELECT 1 FROM batches WHERE hash=?", (digest,)).fetchone():
            return
        for event in page["events"]:
            prior = conn.execute("SELECT sha256 FROM events WHERE source=? AND generation=? AND sequence=?",
                                 (source, event["generation"], event["sequence"])).fetchone()
            if prior and prior[0] != event["sha256"]:
                raise ArchiveError("Conflicting immutable archive sequence")
            conn.execute("INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?)",
                         (source, event["generation"], event["sequence"], event["event_id"], event["sha256"], digest))
        conn.execute("INSERT INTO batches VALUES(?,?,?,?,?)", (digest, source, order, value["stored_at"], size))
        previous = conn.execute("SELECT ingest_order FROM checkpoints WHERE source=?", (source,)).fetchone()
        if not previous or order > previous[0]:
            conn.execute("INSERT OR REPLACE INTO checkpoints VALUES(?,?,?)", (source, page["next_cursor"], order))

    def _reconcile(self):
        with self._db() as conn:
            known = {row[0] for row in conn.execute("SELECT hash FROM batches")}
            paths = list(self._original_files())
            actual = {path.name.removesuffix(".json.gz") for path in paths}
            if known - actual:
                raise ArchiveError("Indexed original is missing; restore archive backup")
            for path in paths:
                digest = path.name.removesuffix(".json.gz")
                if digest not in known:
                    value = self._read_original(path)
                    self._index(conn, digest, value, path.stat().st_size)

    def checkpoint(self, source):
        _text(source, "source")
        with _lock(self.root), self._db() as conn:
            row = conn.execute("SELECT cursor FROM checkpoints WHERE source=?", (source,)).fetchone()
            return row[0] if row else None

    def ingest_page(self, source, page, *, stored_at=None):
        _text(source, "source")
        validate_page(page)
        with _lock(self.root):
            self._reconcile()
            with self._db() as conn:
                row = conn.execute("SELECT cursor FROM checkpoints WHERE source=?", (source,)).fetchone()
                current = row[0] if row else None
                known_batches = set()
                all_known = bool(page["events"])
                for event in page["events"]:
                    old = conn.execute("SELECT sha256,batch FROM events WHERE source=? AND generation=? AND sequence=?",
                                       (source, event["generation"], event["sequence"])).fetchone()
                    if old is not None and old[0] != event["sha256"]:
                        raise ArchiveError("Conflicting archive page retry")
                    if old is None:
                        all_known = False
                    else:
                        known_batches.add(old[1])
                if current == page["next_cursor"] or all_known:
                    if page["events"] and not all_known:
                        raise ArchiveError("Conflicting archive page retry")
                    if not known_batches:
                        known_batches = {r[0] for r in conn.execute(
                            "SELECT b.hash FROM batches b JOIN checkpoints c ON b.source=c.source "
                            "AND b.ingest_order=c.ingest_order WHERE b.source=?", (source,))}
                    for digest in known_batches:
                        self._read_original(self._original_path(digest))
                    return current
                if page["requested_cursor"] != current:
                    raise ArchiveError("Page does not continue the durable local checkpoint")
                stored = _stamp(stored_at or datetime.now(timezone.utc)).isoformat()
                first = conn.execute("SELECT value FROM metadata WHERE key='archive_started_at'").fetchone()
                last_order = conn.execute("SELECT coalesce(max(ingest_order),0) FROM batches").fetchone()[0]
                value = dict(schema=SCHEMA, source=source, ingest_order=max(time.time_ns(), last_order + 1),
                             stored_at=stored, archive_started_at=first[0] if first else stored, page=page)
                raw = canonical_bytes(value)
                digest = hashlib.sha256(raw).hexdigest()
                compressed = gzip.compress(raw, mtime=0)
                # Validate and stage derived writes first; no transaction is committed yet.
                # A conflict must never leave a poison original behind.
                self._index(conn, digest, value, len(compressed))
                self._write_original(digest, compressed)
                conn.commit()
                return page["next_cursor"]

    def rebuild_index(self):
        """Validate all originals before atomically replacing a derived index."""
        with _lock(self.root):
            self._validate_pins()
            candidate = self.root / f".rebuild-{uuid.uuid4()}.sqlite3"
            try:
                with self._db(candidate) as conn:
                    self._tables(conn)
                    for path in self._original_files():
                        value = self._read_original(path)
                        self._index(conn, path.name.removesuffix(".json.gz"), value, path.stat().st_size)
                with candidate.open("rb") as handle:
                    os.fsync(handle.fileno())
                os.replace(candidate, self.root / "index.sqlite3")
                _fsync_dir(self.root)
            finally:
                candidate.unlink(missing_ok=True)

    def iter_events(self, *, source=None, kind=None, dataset=None):
        """Yield originals in ingestion order. Each compressed read is strictly bounded."""
        if source is not None:
            _text(source, "source")
        with _lock(self.root), self._db() as conn:
            rows = conn.execute("SELECT hash FROM batches WHERE (? IS NULL OR source=?) ORDER BY ingest_order,hash",
                                (source, source)).fetchall()
            selected = None
            if dataset is not None:
                pins = self._pins()
                if dataset not in pins:
                    raise ArchiveError("Unknown pinned dataset")
                selected = set(pins[dataset])
                self._validate_pins(pins)
                indexed = {row[0] for row in conn.execute("SELECT hash FROM batches")}
                if not selected <= indexed:
                    raise ArchiveError("Pinned dataset is missing indexed originals; rebuild index")
            seen = set()
            for (digest,) in rows:
                if selected is not None and digest not in selected:
                    continue
                value = self._read_original(self._original_path(digest))
                for event in value["page"]["events"]:
                    key = value["source"], event["generation"], event["sequence"]
                    if key not in seen and (kind is None or event["kind"] == kind):
                        seen.add(key)
                        yield {"source": value["source"], **event}

    def resolve_events(self, event_ids, *, source, generation, dataset=None):
        """Read exact same-generation dependencies through the disposable index.

        Resolve at most one bounded set of references, never search unrelated
        sources or silently reach outside a frozen dataset. A missing or
        ambiguous identifier is an incomplete replay, not an empty result.
        """
        with self.reference_reader(source=source, generation=generation, dataset=dataset) as resolve:
            return resolve(event_ids)

    @contextmanager
    def reference_reader(self, *, source, generation, dataset=None):
        """Verify a frozen selection around many indexed dependency reads.

        No lock is held while the caller works. Required originals are verified
        on every lookup; the whole selected pin is checked at entry and normal
        completion. Publish a result only after this context exits successfully.
        """
        _text(source, "source")
        _generation(generation)
        selected = None
        pinned = None
        if dataset is not None:
            with _lock(self.root):
                pins = self._pins()
                if dataset not in pins:
                    raise ArchiveError("Unknown pinned dataset")
                pinned = tuple(pins[dataset])
                self._validate_pins({dataset: pinned})
                selected = frozenset(pinned)
        active = True

        def resolve(event_ids):
            if not active:
                raise ArchiveError("Reference reader is closed")
            return self._resolve_events(event_ids, source=source, generation=generation, selected=selected)

        try:
            yield resolve
            if dataset is not None:
                with _lock(self.root):
                    pins = self._pins()
                    if dataset not in pins or tuple(pins[dataset]) != pinned:
                        raise ArchiveError("Pinned dataset changed during reference read")
                    self._validate_pins({dataset: pinned})
        finally:
            active = False

    def _resolve_events(self, event_ids, *, source, generation, selected):
        if not isinstance(event_ids, (list, tuple)) or not 1 <= len(event_ids) <= 1024:
            raise ArchiveError("Reference lookup requires between one and 1024 IDs")
        for identifier in event_ids:
            _text(identifier, "event ID")
        if len(set(event_ids)) != len(event_ids):
            raise ArchiveError("Duplicate replay reference")
        with _lock(self.root), self._db() as conn:
            references = {}
            for offset in range(0, len(event_ids), 200):
                chunk = event_ids[offset:offset + 200]
                placeholders = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    "SELECT event_id,sequence,sha256,batch FROM events "
                    f"WHERE source=? AND generation=? AND event_id IN ({placeholders})",
                    (source, generation, *chunk),
                )
                for identifier, sequence, digest, batch in rows:
                    if identifier in references:
                        raise ArchiveError("Ambiguous replay reference")
                    if selected is not None and batch not in selected:
                        raise ArchiveError("Replay reference lies outside pinned dataset")
                    references[identifier] = (sequence, digest, batch)
            if len(references) != len(event_ids):
                raise ArchiveError("Missing replay reference")
            batches = {}
            for identifier, (sequence, digest, batch) in references.items():
                batches.setdefault(batch, {})[identifier] = (sequence, digest)
            resolved = {}
            for batch, wanted in batches.items():
                original = self._read_original(self._original_path(batch))
                if original["source"] != source:
                    raise ArchiveError("Replay reference index disagrees with original source")
                for event in original["page"]["events"]:
                    identifier = event["event_id"]
                    if identifier not in wanted:
                        continue
                    if (event["generation"] != generation
                            or (event["sequence"], event["sha256"]) != wanted[identifier]
                            or identifier in resolved):
                        raise ArchiveError("Replay reference index disagrees with original event")
                    resolved[identifier] = {"source": source, **event}
            if len(resolved) != len(event_ids):
                raise ArchiveError("Replay reference absent from indexed original")
            return [resolved[identifier] for identifier in event_ids]

    def pin(self, dataset, *, sources=None):
        """Freeze all original files currently belonging to selected sources."""
        _text(dataset, "dataset", 128)
        with _lock(self.root), self._db() as conn:
            if sources is not None and (not isinstance(sources, list) or not sources):
                raise ArchiveError("Pinned sources must be a nonempty list")
            if sources is not None:
                for source in sources:
                    _text(source, "source")
            selected = set(sources) if sources is not None else None
            pins = self._pins()
            self._validate_pins(pins)
            if dataset in pins:
                raise ArchiveError("Dataset already pinned; pins are immutable")
            pins[dataset] = [digest for digest, source in conn.execute("SELECT hash,source FROM batches")
                             if selected is None or source in selected]
            self._validate_pins(pins)
            raw = canonical_bytes(dict(schema=SCHEMA, datasets=pins))
            if len(raw) > 4 * 1024 * 1024:
                raise ArchiveError("Pin manifest exceeds bound")
            _atomic(self.root, "pins.json", raw)
            return pins[dataset]

    def export_dataset(self, dataset, destination, *, layout="hash-prefix"):
        """Copy a frozen original set and its manifest; never overwrite a destination."""
        target = Path(destination)

        def validate_target():
            if (Path(os.path.abspath(target)).is_relative_to(Path(os.path.abspath(self.root)))
                    or target.resolve().is_relative_to(self.root.resolve())):
                raise ArchiveError("Dataset destination must stay outside the source archive")

        validate_target()
        self._layout_path("0" * 64, layout)
        with _lock(self.root):
            pins = self._pins()
            self._validate_pins(pins)
            if dataset not in pins:
                raise ArchiveError("Unknown pinned dataset")
            if target.exists():
                raise ArchiveError("Dataset destination already exists")
            verified = []
            sources = {}
            for digest in pins[dataset]:
                path = self._original_path(digest)
                value = self._read_original(path)
                stamps = [event["received_at"] for event in value["page"]["events"]]
                summary = sources.setdefault(value["source"], {"events": 0, "first_received_at": None, "last_received_at": None})
                summary["events"] += len(stamps)
                if stamps:
                    summary["first_received_at"] = min([*stamps, summary["first_received_at"]] if summary["first_received_at"] else stamps)
                    summary["last_received_at"] = max([*stamps, summary["last_received_at"]] if summary["last_received_at"] else stamps)
                verified.append((digest, path))
            validate_target()
            target.mkdir(parents=True, mode=0o700)
            originals = target / "originals"
            originals.mkdir(mode=0o700)
            exported = ArchiveStore.__new__(ArchiveStore)
            exported.root, exported.originals = target, originals
            for digest, path in verified:
                exported._write_original(digest, path.read_bytes(), layout=layout)
            manifest = dict(schema=SCHEMA, dataset=dataset, original_sha256=pins[dataset], sources=sources,
                            integrity_only=True, completeness="requires replay dependency validation")
            _atomic(target, "dataset.json", canonical_bytes(manifest))
            _atomic(target, "pins.json", canonical_bytes(dict(schema=SCHEMA, datasets={dataset: pins[dataset]})))
            _fsync_dir(target.parent)
            return manifest

    def _pins(self):
        path = self.root / "pins.json"
        if not path.exists():
            return {}
        try:
            with path.open("rb") as handle:
                raw = handle.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise ArchiveError("Pin manifest exceeds bound")
            value = json.loads(raw)
            if set(value) != {"schema", "datasets"} or type(value["schema"]) is not int or value["schema"] != SCHEMA or not isinstance(value["datasets"], dict):
                raise ArchiveError("Malformed pin manifest")
            for name, hashes in value["datasets"].items():
                _text(name, "dataset", 128)
                if not isinstance(hashes, list) or any(not isinstance(h, str) or len(h) != 64 or any(c not in "0123456789abcdef" for c in h) for h in hashes):
                    raise ArchiveError("Malformed pin hashes")
            return value["datasets"]
        except (ValueError, TypeError, OSError) as exc:
            raise ArchiveError("Invalid pin manifest; retention aborted") from exc

    def _validate_pins(self, pins=None):
        """Do not turn a missing pinned original into a silently partial dataset."""
        pins = self._pins() if pins is None else pins
        for digest in {digest for hashes in pins.values() for digest in hashes}:
            if not self._original_path(digest).is_file():
                raise ArchiveError("Pinned original is missing; restore archive backup")
        return pins

    def maintain(self, *, now=None):
        """Explicit 24-calendar-month maintenance; keep pins and latest source checkpoint."""
        stamp = _stamp(now or datetime.now(timezone.utc))
        cutoff = _months_before(stamp, 24)
        with _lock(self.root):
            pinned = {digest for hashes in self._validate_pins().values() for digest in hashes}
            self._reconcile()
            with self._db() as conn:
                # Latest page is retained even when empty: it is the reconstructible checkpoint.
                latest = {row[0] for row in conn.execute("SELECT b.hash FROM batches b JOIN checkpoints c ON b.source=c.source AND b.ingest_order=c.ingest_order")}
                expired = [digest for digest, when in conn.execute("SELECT hash,stored_at FROM batches")
                           if _stamp(when) < cutoff and digest not in pinned | latest]
                # Delete derived rows first; a crash can leave an original (safe extra retention).
                for digest in expired:
                    conn.execute("DELETE FROM events WHERE batch=?", (digest,))
                    conn.execute("DELETE FROM batches WHERE hash=?", (digest,))
                conn.commit()
                for digest in expired:
                    for layout in ("flat", "hash-prefix"):
                        path = self._layout_path(digest, layout)
                        if path.exists():
                            path.unlink()
                            _fsync_dir(path.parent)
                _fsync_dir(self.originals)
                conn.execute("VACUUM")
                return dict(removed_batches=len(expired), cutoff=cutoff.isoformat(), retained_pinned=len(pinned))

    def verify(self):
        """Verify every bounded original without changing the derived index."""
        with _lock(self.root):
            self._validate_pins()
            with self._db(check_integrity=True):
                pass
            for path in self._original_files():
                self._read_original(path)
            self._reconcile()
        return True

    def stats(self, *, now=None):
        stamp = _stamp(now or datetime.now(timezone.utc))
        with _lock(self.root), self._db() as conn:
            counts = conn.execute("SELECT count(*),coalesce(sum(bytes),0),min(stored_at) FROM batches").fetchone()
            event_count = conn.execute("SELECT count(*) FROM events").fetchone()[0]
            started = conn.execute("SELECT value FROM metadata WHERE key='archive_started_at'").fetchone()
            first = _stamp(started[0]) if started else stamp
            days = max((stamp - first).total_seconds() / 86400, 1)
            by_source = {source: dict(batches=count, compressed_bytes=size)
                         for source, count, size in conn.execute("SELECT source,count(*),sum(bytes) FROM batches GROUP BY source")}
            return dict(schema=SCHEMA, batches=counts[0], events=event_count, compressed_bytes=counts[1],
                        index_bytes=(self.root / "index.sqlite3").stat().st_size, by_source=by_source,
                        observation_days=days, compressed_bytes_per_day=counts[1] / days,
                        projected_24_month_compressed_bytes=counts[1] / days * 731,
                        capacity_review_3_months_at=_months_before(first, -3).isoformat(),
                        capacity_review_6_months_at=_months_before(first, -6).isoformat(),
                        pinned_datasets=len(self._pins()))


# Public spelling for collectors validating individual envelopes.
verify_event = validate_envelope
