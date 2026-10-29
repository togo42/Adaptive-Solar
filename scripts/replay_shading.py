#!/usr/bin/env python3
"""Stream a complete archived shade-learning episode to JSONL, without HA writes."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.adaptive_solar.archive_export import json_value
from custom_components.adaptive_solar.core.archive import ArchiveStore, canonical_bytes
from custom_components.adaptive_solar.core.replay import hydrate_forecast, timestamp
from custom_components.adaptive_solar.core.shade_learning import ShadeLearningPolicy
from custom_components.adaptive_solar.core.shade_replay import ShadeCandidate, replay_shading_stream
from scripts.replay_paths import publish_output, validate_output



class _References:
    """One validated pin context per generation, closed before publication."""

    def __init__(self, store, contexts):
        self.store = store
        self.contexts = contexts
        self.readers = {}

    def iter_events(self, **kwargs):
        return self.store.iter_events(**kwargs)

    def resolve_events(self, event_ids, *, source, generation, dataset):
        key = source, generation, dataset
        if key not in self.readers:
            self.readers[key] = self.contexts.enter_context(self.store.reference_reader(
                source=source, generation=generation, dataset=dataset))
        return self.readers[key](event_ids)

def _resolve(store, source, dataset, generation, wanted):
    if not wanted:
        return []
    return store.resolve_events(sorted(wanted), source=source, generation=generation, dataset=dataset)



def _reference_bytes(reference, dependencies):
    if reference.get("encoding") == "zlib+base64":
        size = reference.get("uncompressed_bytes")
        if type(size) is not int or not 0 < size <= 128 * 1024 * 1024:
            raise ValueError("invalid declared decompressed byte bound")
        return size
    wanted = set(reference.get("event_ids", []))
    return sum(len(row["payload"].get("json_fragment", "").encode()) for row in dependencies if row["event_id"] in wanted)


def _payload_bytes(event, dependencies):
    reference = event["payload"].get("payload_ref")
    return _reference_bytes(reference, dependencies) if reference else len(canonical_bytes(event["payload"]))


def _check_decoded(size, maximum):
    if size > maximum:
        raise ValueError("one replay step exceeds declared decompressed/serialized byte budget (not peak RSS)")

def _dependencies(store, source, dataset, event, max_decoded_bytes=256 * 1024 * 1024):
    """Resolve only one step's payload, state and original-weather closure."""
    chunks = _resolve(store, source, dataset, event["generation"], set(event["payload"].get("payload_ref", {}).get("event_ids", [])))
    payload_bytes = _payload_bytes(event, chunks)
    _check_decoded(payload_bytes, max_decoded_bytes)
    resolved = hydrate_forecast(event, chunks)
    state_reference = resolved["payload"]["replay_state"]
    _check_decoded(payload_bytes + _reference_bytes(state_reference, []), max_decoded_bytes)
    wanted = set(resolved["payload"]["replay_state"]["event_ids"])
    wanted.update(resolved["payload"].get("weather_receipt_ids", {}).values())
    state_weather = _resolve(store, source, dataset, event["generation"], wanted)
    decoded = payload_bytes + _reference_bytes(state_reference, state_weather)
    decoded += sum(_payload_bytes(row, []) for row in state_weather if row["kind"] == "weather_response")
    _check_decoded(decoded, max_decoded_bytes)
    weather_chunks = _resolve(store, source, dataset, event["generation"], {identifier for row in state_weather if row["kind"] == "weather_response"
                              for identifier in row["payload"].get("payload_ref", {}).get("event_ids", [])})
    decoded = payload_bytes + _reference_bytes(state_reference, state_weather)
    decoded += sum(_payload_bytes(row, weather_chunks) for row in state_weather if row["kind"] == "weather_response")
    _check_decoded(decoded, max_decoded_bytes)
    return resolved, chunks + state_weather + weather_chunks


def _spool(store, source, dataset, connection, as_of, max_decoded_bytes):
    """Disk spool avoids retaining all manifests or nested ArchiveStore locks."""
    connection.execute("CREATE TABLE issued (position INTEGER PRIMARY KEY, event TEXT, session TEXT, step INTEGER)")
    for event in store.iter_events(source=source, kind="forecast_issued", dataset=dataset):
        if as_of is None or timestamp(event["received_at"]) <= as_of:
            connection.execute("INSERT INTO issued(event) VALUES (?)", (json.dumps(event, separators=(",", ":")),))
    connection.commit()
    sessions, missing = set(), 0
    for position, encoded in connection.execute("SELECT position,event FROM issued"):
        event = json.loads(encoded)
        chunks = _resolve(store, source, dataset, event["generation"], set(event["payload"].get("payload_ref", {}).get("event_ids", [])))
        _check_decoded(_payload_bytes(event, chunks), max_decoded_bytes)
        event = hydrate_forecast(event, chunks)
        learning = event["payload"].get("shade_learning")
        session = learning.get("session_id") if isinstance(learning, dict) else None
        step = learning.get("step_sequence") if isinstance(learning, dict) else None
        if not isinstance(session, str) or not session or type(step) is not int:
            missing += 1
            continue
        sessions.add(session)
        connection.execute("UPDATE issued SET session=?,step=? WHERE position=?", (session, step, position))
    connection.commit()
    return sessions, missing


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--dataset", required=True, help="Immutable ArchiveStore dataset pin")
    parser.add_argument("--output", type=Path, required=True, help="JSONL: one step per line followed by final summary")
    parser.add_argument("--session-id", help="Required when capture contains multiple sessions or legacy events")
    parser.add_argument("--as-of", type=timestamp)
    parser.add_argument("--max-decoded-mib", type=int, default=256,
                        help="Per-step declared decompressed/serialized bytes; does not bound Python peak RSS")
    parser.add_argument("--initial-state", choices=("recorded", "empty"), default="recorded")
    parser.add_argument("--candidate-min-clearness", type=float, default=.8,
                        help="Experimental clear-sky GHI ratio gate (original is 0.6)")
    args = parser.parse_args()
    temporary_output = None
    try:
        inputs = (Path(__file__),)
        validate_output(args.output, args.archive, inputs)
        if args.max_decoded_mib <= 0:
            raise ValueError("max-decoded-mib must be positive")
        max_decoded_bytes = args.max_decoded_mib * 1024 * 1024
        store = ArchiveStore(args.archive)
        version = f"clearness-{args.candidate_min_clearness:.17g}-v1"
        policy = ShadeLearningPolicy(version=version, min_clearness_index=args.candidate_min_clearness)
        control = ShadeLearningPolicy()
        candidates = (ShadeCandidate("shade_control", control.version, control), ShadeCandidate("clearness_candidate", version, policy))
        with ExitStack() as reference_contexts:
            references = _References(store, reference_contexts)
            with tempfile.TemporaryDirectory(prefix="shade-replay-") as scratch:
                with sqlite3.connect(Path(scratch) / "issued.sqlite") as connection:
                    sessions, missing = _spool(references, args.source, args.dataset, connection, args.as_of, max_decoded_bytes)
                    if args.session_id is None and (len(sessions) != 1 or missing):
                        raise ValueError("select --session-id for multiple sessions or legacy/missing capture contracts")
                    session = args.session_id or next(iter(sessions), None)
                    if session not in sessions:
                        raise ValueError("no matching declared shade session")
                    digest = hashlib.sha256()

                    def steps():
                        for (encoded,) in connection.execute("SELECT event FROM issued WHERE session=? ORDER BY step,position", (session,)):
                            event, dependencies = _dependencies(references, args.source, args.dataset, json.loads(encoded), max_decoded_bytes)
                            digest.update(canonical_bytes({"event": event["sha256"], "dependencies": sorted(row["sha256"] for row in dependencies)}))
                            yield event, dependencies

                    validate_output(args.output, args.archive, inputs)
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    descriptor, name = tempfile.mkstemp(prefix=f".{args.output.name}.", suffix=".tmp", dir=args.output.parent)
                    temporary_output = Path(name)
                    summary = None
                    with os.fdopen(descriptor, "w") as output:
                        for row in replay_shading_stream(steps(), candidates=candidates, initial_state=args.initial_state,
                                                        session_id=session, as_of=args.as_of):
                            if row["record_type"] == "summary":
                                row.update(dataset=args.dataset, selected_envelopes_sha256=digest.hexdigest(),
                                           max_decoded_bytes_per_step=max_decoded_bytes, byte_budget_scope="declared_decompressed_and_serialized_not_peak_rss",
                                           replay_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
                                summary = row
                            output.write(json.dumps(json_value(row), sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")
                        output.flush()
                        os.fsync(output.fileno())
                    if summary is None:
                        raise ValueError("shade stream lacks completion summary")
        # Pin validation in every reference context must finish first.
        publish_output(temporary_output, args.output, args.archive, inputs)
        temporary_output = None
        accepted = summary["baseline"]["accepted"]
        print(json.dumps({"status": "accepted" if accepted else "baseline_mismatch", "steps": summary["step_count"],
                          "output": str(args.output)}))
        return 0 if accepted else 1
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error) as err:
        print(f"Shade replay failed: {type(err).__name__}: {err}", file=sys.stderr)
        return 2
    finally:
        if temporary_output is not None:
            temporary_output.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
