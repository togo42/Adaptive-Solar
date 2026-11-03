"""Explicitly pinned selection for one frozen archive/query, never a live cache.

Building a plan validates the complete corpus and index. Every reuse hashes all
compressed originals and the index before/after its scope; selected originals
and references still use native validation. Build costs are separate evidence.
"""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time

SCHEMA = "adaptive-solar-frozen-quality-selection-v1"
JSON_SETTINGS = dict(sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
MAX_BYTES = 4 * 1024**3
RESERVE_FRAMES = 64
REUSE_MARGIN = 32


def _canonical(value):
    pending, seen = [value], set()
    while pending:
        item = pending.pop()
        if isinstance(item, (dict, list, tuple)) and id(item) not in seen:
            seen.add(id(item))
            if isinstance(item, dict):
                if any(not isinstance(key, str) for key in item):
                    raise ValueError("Selection JSON requires string keys")
                pending.extend(item.values())
            else:
                pending.extend(item)
    return json.dumps(value, **JSON_SETTINGS).encode("utf-8")


def plan_sha256(plan):
    """Canonical document SHA; the caller must pin this outside the plan."""
    return hashlib.sha256(_canonical(plan)).hexdigest()


def _file_sha(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            result.update(chunk)
    return result.hexdigest()


def _utc(value):
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("Selection timestamps require offsets")
    return stamp.astimezone(UTC)


def query_from_capture(raw, bindings, *, pin_raw=True):
    """Bind exact targets/policy; receipt/as_of never exclude original evidence.

    The default raw pin narrows reuse to this exact captured document. Turning
    it off still binds the complete policy and target, not an arbitrary query.
    """
    if bindings.get("schema") != "adaptive-solar-actual-quality-bindings-v2":
        raise ValueError("Selection requires an explicit continuous policy")
    start, end = (_utc(raw["raw"][key]) for key in ("target_start", "target_end"))
    if not start < end or any(t.minute or t.second or t.microsecond for t in (start, end)):
        raise ValueError("Selection requires complete UTC target hours")
    rows = bindings["bindings"]
    if not isinstance(rows, list) or len(rows) > 1024:
        raise ValueError("Selection policy exceeds binding limit")
    periods = []
    for row in rows:
        if not all(isinstance(row[key], str) and row[key] for key in ("source", "config_event_id")):
            raise ValueError("Invalid selection source or anchor")
        a, b = _utc(row["valid_from"]), _utc(row["valid_to"])
        if a >= b:
            raise ValueError("Invalid selection policy period")
        periods.append(dict(source=row["source"], anchor=row["config_event_id"], start=a.isoformat(), end=b.isoformat()))
    result = dict(schema=SCHEMA, start=start.isoformat(), end=end.isoformat(),
                  bindings_sha256=plan_sha256(bindings), periods=periods)
    if pin_raw:
        result["raw_sha256"] = plan_sha256(raw)
    return result


def _native(reader):
    for cls in type(reader).__mro__:
        module = sys.modules.get(cls.__module__)
        if cls.__name__ == "ArchiveStore" and module and Path(module.__file__).name == "archive.py":
            root = Path(module.__file__).resolve().parents[3]
            if root != Path(__file__).resolve().parents[1]:
                raise ValueError("Selection helper and native reader must share the pinned source root")
            for name in ("_read_original", "_original_files", "_original_path", "_layout_path", "iter_events",
                         "resolve_events", "reference_reader", "_resolve_events", "_event_batches", "_pins", "_validate_pins"):
                if name in vars(reader) or getattr(getattr(reader, name), "__func__", None) is not getattr(cls, name):
                    raise ValueError("Custom reader overrides are unsupported for frozen selection proofs")
            return cls, module, root
    raise ValueError("A native ArchiveStore reader is required")


def _pins(reader):
    _, module, root = _native(reader)
    paths, total = [], 0
    candidates = [*root.iterdir()]
    for folder in ("custom_components", "scripts"):
        candidates.extend((root / folder).rglob("*"))
    for path in candidates:
        if path.is_symlink() or path.name == "__pycache__" or path.suffix in {".pyc", ".pyo"}:
            raise ValueError("Selection sources must be cache-free regular source files")
        if path.is_file() and path.suffix in {".py", ".json"}:
            paths.append(str(path.relative_to(root)))
            total += path.stat().st_size
            if len(paths) > 2000 or total > 128 * 1024**2:
                raise ValueError("Selection source inventory exceeds budget")
    return dict(files={name: _file_sha(root / name) for name in paths}, python=sys.version,
                recursion_limit=sys.getrecursionlimit(), int_max_str_digits=sys.get_int_max_str_digits(),
                selection_limits=dict(reserve_frames=RESERVE_FRAMES, reuse_margin=REUSE_MARGIN),
                json_settings={**JSON_SETTINGS, "separators": list(JSON_SETTINGS["separators"])},
                native_limits={key: getattr(module, key) for key in
                               ("SCHEMA", "MAX_EVENT_BYTES", "MAX_PAGE_BYTES", "MAX_PAGE_EVENTS")})


@contextmanager
def _db(root):
    connection = sqlite3.connect((root / "index.sqlite3").as_uri() + "?mode=ro&immutable=1")
    try:
        connection.execute("PRAGMA query_only=ON")
        yield connection
    finally:
        connection.close()


def _limits(max_batches, max_events, max_bytes):
    if (not 1 <= max_batches <= 50000 or not 1 <= max_events <= 2000000 or not 1 <= max_bytes <= MAX_BYTES):
        raise ValueError("Frozen selection budgets exceed supported bounds")
    return dict(max_batches=max_batches, max_events=max_events, max_bytes=max_bytes)


def _snapshot(reader, query, limits):
    root = Path(reader.root).resolve()
    if Path(reader.root).is_symlink() or any((root / ("index.sqlite3" + suffix)).exists()
                                           for suffix in ("-wal", "-shm", "-journal")):
        raise ValueError("Selection requires a frozen archive without symlinks or SQLite sidecars")
    files, total, decompressed = {}, 0, 0
    for path in reader._original_files():
        relative = str(path.relative_to(root))
        size = path.stat().st_size
        total += size
        if size < 4:
            raise ValueError("Frozen original is not a complete gzip file")
        with path.open("rb") as stream:
            stream.seek(-4, 2)
            decompressed += int.from_bytes(stream.read(4), "little")
        if len(files) >= limits["max_batches"] or total > limits["max_bytes"]:
            raise ValueError("Frozen selection corpus exceeds budget")
        if decompressed > limits["max_bytes"]:
            raise ValueError("Frozen selection decompressed-size inventory exceeds budget")
        files[relative] = dict(sha256=_file_sha(path), bytes=size, digest=path.name.removesuffix(".json.gz"))
    index = root / "index.sqlite3"
    if not index.is_file() or index.is_symlink() or index.stat().st_size > limits["max_bytes"]:
        raise ValueError("Frozen selection index is missing or oversized")
    return dict(files=files, index_sha256=_file_sha(index), compressed_bytes=total, gzip_isize_bytes=decompressed,
                query=json.loads(_canonical(query)), pins=_pins(reader))


def _relevant(event, source, query):
    periods = [p for p in query["periods"] if p["source"] == source]
    if not periods:
        return False
    try:
        payload = event["payload"]
        if event["kind"] == "qualified_interval":
            return _utc(payload["start"]) < _utc(query["end"]) and _utc(payload["end"]) > _utc(query["start"])
        if event["kind"] == "forecast_issued":
            return any(event["event_id"] == p["anchor"] for p in periods) or any(
                _utc(p["start"]) <= _utc(payload["issued_at"]) < _utc(p["end"]) for p in periods)
        return False
    except (KeyError, TypeError, ValueError, OverflowError):
        # Preserve the consumer's own receipt filter and validation/error order.
        return True


def _headroom():
    depth, frame = 0, sys._getframe()
    while frame:
        depth += 1
        frame = frame.f_back
    return sys.getrecursionlimit() - depth


def _proof_read(reader, path, reserve):
    if reserve:
        return _proof_read(reader, path, reserve - 1)
    headroom = _headroom()
    return reader._read_original(path), headroom


def _recursion_failure(error):
    seen = set()
    while error is not None and id(error) not in seen:
        if isinstance(error, RecursionError):
            return True
        seen.add(id(error))
        error = error.__cause__ or error.__context__
    return False


def build_plan(reader, query, *, max_batches=50000, max_events=2000000, max_bytes=MAX_BYTES):
    """Cold full validation, including authoritative batch/event-index completeness."""
    if query.get("schema") != SCHEMA:
        raise ValueError("Unsupported frozen selection query")
    wall, cpu = time.perf_counter(), time.process_time()
    limits = _limits(max_batches, max_events, max_bytes)
    before = _snapshot(reader, query, limits)
    root, catalog, witnesses, selected = Path(reader.root).resolve(), {}, {}, set()
    event_count = proof_headroom = 0
    for relative, info in before["files"].items():
        forced = False
        try:
            value, headroom = _proof_read(reader, root / relative, RESERVE_FRAMES)
        except (ValueError, RecursionError) as error:
            if not _recursion_failure(error):
                raise
            value, headroom = reader._read_original(root / relative), 0
            forced = True
        batch = info["digest"]
        metadata = dict(source=value["source"], ingest_order=value["ingest_order"], stored_at=value["stored_at"])
        if batch in catalog and catalog[batch] != metadata:
            raise ValueError("Conflicting original batch metadata")
        catalog[batch] = metadata
        take = forced
        for event in value["page"]["events"]:
            event_count += 1
            if event_count > limits["max_events"]:
                raise ValueError("Frozen selection event budget exceeded")
            key = value["source"], event["generation"], event["sequence"]
            entry = witnesses.setdefault(key, (event["event_id"], event["sha256"], set()))
            if entry[:2] != (event["event_id"], event["sha256"]):
                raise ValueError("Conflicting immutable original sequence")
            entry[2].add(batch)
            take |= _relevant(event, value["source"], query)
        if take:
            selected.add(batch)
        else:
            proof_headroom = max(proof_headroom, headroom)
    with _db(root) as conn:
        if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("Frozen index is corrupt")
        if (conn.execute("PRAGMA user_version").fetchone()[0] != before["pins"]["native_limits"]["SCHEMA"]
                or conn.execute("SELECT value FROM metadata WHERE key='kind'").fetchone() != ("host",)):
            raise ValueError("Frozen index format is unsupported")
        rows = list(conn.execute("SELECT hash,source,ingest_order,stored_at,bytes FROM batches"))
        if len(rows) != len(catalog):
            raise ValueError("Frozen batch index is incomplete")
        remaining_batches = dict(catalog)
        for batch, source, order, stored, size in rows:
            if remaining_batches.pop(batch, None) != dict(source=source, ingest_order=order, stored_at=stored):
                raise ValueError("Frozen batch index disagrees with originals")
            if size != reader._original_path(batch).stat().st_size:
                raise ValueError("Frozen batch byte index disagrees with originals")
        for source, generation, sequence, identifier, sha, batch in conn.execute(
                "SELECT source,generation,sequence,event_id,sha256,batch FROM events"):
            entry = witnesses.pop((source, generation, sequence), None)
            if entry is None or entry[:2] != (identifier, sha) or batch not in entry[2]:
                raise ValueError("Frozen event/reference index disagrees with originals")
        if witnesses:
            raise ValueError("Frozen event/reference index is incomplete")
        if remaining_batches:
            raise ValueError("Frozen batch index is incomplete")
    if _snapshot(reader, query, limits) != before:
        raise ValueError("Frozen corpus changed while building selection plan")
    return dict(schema=SCHEMA, snapshot=before, catalog=catalog, selected=sorted(selected), limits=limits,
                required_headroom=proof_headroom, reserve_frames=RESERVE_FRAMES, reuse_margin=REUSE_MARGIN,
                build=dict(wall_seconds=time.perf_counter() - wall, cpu_seconds=time.process_time() - cpu,
                           validated_events=event_count, original_files=len(before["files"])),
                scope="One frozen corpus/query; cold full build and warm reuse are separate measurements")


@contextmanager
def selection_scope(reader, plan, *, expected_plan_sha256, query):
    """Yield a read-only native subclass; external plan pin is mandatory."""
    expected = expected_plan_sha256
    if (not isinstance(expected, str) or len(expected) != 64 or plan_sha256(plan) != expected
            or plan.get("schema") != SCHEMA or plan["reserve_frames"] != RESERVE_FRAMES
            or plan["reuse_margin"] != REUSE_MARGIN):
        raise ValueError("Frozen selection plan pin mismatch")
    limits = _limits(**plan["limits"])
    if _snapshot(reader, query, limits) != plan["snapshot"]:
        raise ValueError("Frozen selection inputs, query or source/runtime pins changed")
    native, _, _ = _native(reader)
    selected = frozenset(plan["selected"])
    sources = frozenset(p["source"] for p in query["periods"])
    required_headroom, reuse_margin = plan["required_headroom"], plan["reuse_margin"]
    iterators = []

    class SelectedArchiveView(type(reader)):
        def __getattribute__(self, name):
            if not name.startswith("_") and name not in {"root", "originals", "iter_events", "resolve_events", "reference_reader", "selection_status"}:
                raise ValueError("Frozen selection exposes read-only quality operations")
            if name in {"iter_events", "resolve_events", "reference_reader"} and not object.__getattribute__(self, "_selection_active"):
                raise ValueError("Frozen selection scope is closed")
            return super().__getattribute__(name)

        def _read_lock(self, *, source=None):
            if not self._selection_active or source not in sources:
                raise ValueError("Frozen selection scope/source is unsupported")
            return nullcontext()

        def _db(self, path=None, **kwargs):
            if not self._selection_active or (path is not None and Path(path).resolve() != root / "index.sqlite3"):
                raise ValueError("Frozen selection database access is unsupported")
            return _db(root)

        def _pins(self):
            raise ValueError("Frozen quality selection does not support datasets")

        def _event_batches(self, conn, source):
            rows = native._event_batches(self, conn, source)
            self._selection_candidates += len(rows)
            if _headroom() < required_headroom + reuse_margin:
                self._selection_fallbacks += 1
                self._selection_scheduled += len(rows)
                return rows
            chosen = [row for row in rows if row[0] in selected]
            self._selection_scheduled += len(chosen)
            return chosen

        @property
        def selection_status(self):
            return dict(headroom_fallbacks=self._selection_fallbacks, candidate_batches=self._selection_candidates,
                        scheduled_batches=self._selection_scheduled, active=self._selection_active)

        def iter_events(self, *, source=None, kind=None, dataset=None):
            if not self._selection_active or source not in sources or kind is not None or dataset is not None:
                raise ValueError("Frozen selection iteration query is unsupported")
            if len(iterators) >= 1024:
                raise ValueError("Frozen selection iterator limit exceeded")
            iterator = native.iter_events(self, source=source)
            iterators.append(iterator)
            return iterator

    root = Path(reader.root).resolve()
    view = object.__new__(SelectedArchiveView)
    view.__dict__.update(reader.__dict__)
    view._selection_active, view._selection_fallbacks = True, 0
    view._selection_candidates = view._selection_scheduled = 0
    try:
        yield view
    finally:
        for iterator in iterators:
            iterator.close()
        view._selection_active = False
        if plan_sha256(plan) != expected or _snapshot(reader, query, limits) != plan["snapshot"]:
            raise ValueError("Frozen selection scope inputs or plan changed")
