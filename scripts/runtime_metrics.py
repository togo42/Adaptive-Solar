"""Bounded, sanitized monotonic phase evidence for archive job wrappers.

This module never records commands, environments, outputs or exception text.
It performs no filesystem operations except closing an explicitly supplied
lock handle. Optional event sinks receive only the fixed phase schema.
"""
from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
import math
import re
import subprocess
import threading
import time
from uuid import uuid4

SCHEMA = "adaptive-solar-archive-runtime-v1"
PHASES = frozenset({
    "lock_open", "lock_wait", "job_prepare", "capacity", "child_run", "stats", "result_write", "lock_close",
    "store_init", "store_reconcile", "recorder_capture", "recovery", "quality_derive",
    "quality_source_scan", "quality_config_projection", "quality_build", "archive_append",
    "archive_collect", "payload_resolve", "normalization", "original_read",
})


def failure_kind(error):
    """Fixed categories only; never access exception arguments or repr/text."""
    if isinstance(error, subprocess.TimeoutExpired):
        return "timeout"
    if isinstance(error, OSError):
        return "os_error"
    if isinstance(error, (ValueError, TypeError, KeyError)):
        return "invalid_data"
    if not isinstance(error, Exception):
        return "interrupted"
    return "internal_error"


class _Span:
    def __init__(self, recorder, phase, ordinal, timeout_seconds, emit_events):
        self.recorder, self.phase = recorder, phase
        self.ordinal, self.timeout_seconds = ordinal, timeout_seconds
        self.emit_events = emit_events
        self.row = None

    def __enter__(self):
        self.row = self.recorder._start(self.phase, self.ordinal, self.timeout_seconds, self.emit_events)
        return self

    def exited(self, returncode):
        if type(returncode) is not int or not -(2**31) <= returncode < 2**31:
            raise ValueError("Runtime process return code must be an integer")
        with self.recorder._lock:
            self.row.update(exit_kind="exited", returncode=returncode)

    def __exit__(self, _type, error, _traceback):
        self.recorder._end(self.row, error, self.emit_events)
        return False


class PhaseRecorder:
    """Independent spans allow nested/overlapping work without inventing time.

    Durations are inclusive; overlapping spans must not be summed as total job
    time. Bounded details retain the most recent spans. Silent hot-path
    spans update aggregates/active phases without consuming detail slots.
    """

    def __init__(self, job, *, run_id=None, sink=None, clock=None, cpu_clock=None, max_events=512):
        if not isinstance(job, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", job):
            raise ValueError("Invalid runtime job label")
        if type(max_events) is not int or not 1 <= max_events <= 4096:
            raise ValueError("Invalid runtime event budget")
        self.run_id = run_id or str(uuid4())
        if not isinstance(self.run_id, str) or not re.fullmatch(r"[0-9a-f-]{36}", self.run_id):
            raise ValueError("Invalid runtime run identifier")
        self.job, self.sink = job, sink
        self.clock = clock or time.monotonic_ns
        self.cpu_clock = cpu_clock or time.process_time_ns
        self.started_ns = self.clock()
        self.started_cpu_ns = self.cpu_clock()
        self.started_at = datetime.now(UTC).isoformat()
        self.max_events = max_events
        self._lock = threading.Lock()
        self._events, self._active, self._summary = deque(maxlen=max_events), {}, {}
        self._next = self._dropped = self._sink_failures = 0
        self._finished = None

    def phase(self, phase, *, ordinal=None, timeout_seconds=None, emit_events=True):
        if not isinstance(phase, str) or phase not in PHASES:
            raise ValueError("Unsupported runtime phase")
        if ordinal is not None and (type(ordinal) is not int or not 0 <= ordinal < 2**31):
            raise ValueError("Invalid runtime phase ordinal")
        if timeout_seconds is not None and (type(timeout_seconds) not in (int, float)
                or not math.isfinite(timeout_seconds) or not 0 <= timeout_seconds <= 86400):
            raise ValueError("Invalid runtime timeout")
        if type(emit_events) is not bool:
            raise ValueError("Invalid runtime event mode")
        return _Span(self, phase, ordinal, timeout_seconds, emit_events)

    def process(self, phase, function, *args, ordinal=None, **kwargs):
        """Observe a native subprocess call; its private arguments stay opaque."""
        if phase not in {"child_run", "stats"}:
            raise ValueError("Unsupported runtime process phase")
        with self.phase(phase, ordinal=ordinal, timeout_seconds=kwargs.get("timeout")) as span:
            result = function(*args, **kwargs)
            span.exited(result.returncode)
        return result

    def _emit(self, row):
        if self.sink is not None:
            try:
                self.sink({"schema": SCHEMA, "job": self.job, "run_id": self.run_id, **deepcopy(row)})
            except Exception:
                with self._lock:
                    self._sink_failures += 1

    def _start(self, phase, ordinal, timeout_seconds, emit_events):
        started = self.clock()
        started_cpu = self.cpu_clock()
        with self._lock:
            if self._finished is not None:
                raise ValueError("Runtime recorder is already closed")
            self._next += 1
            row = dict(index=self._next, phase=phase, status="active",
                       started_offset_ns=max(0, started - self.started_ns), duration_ns=None,
                       started_cpu_offset_ns=max(0, started_cpu - self.started_cpu_ns),
                       duration_cpu_ns=None, outcome=None)
            if ordinal is not None:
                row["ordinal"] = ordinal
            if timeout_seconds is not None:
                row["timeout_seconds"] = timeout_seconds
            self._active[row["index"]] = (row, started, started_cpu)
            if emit_events:
                if len(self._events) == self.max_events:
                    self._dropped += 1
                self._events.append(row)
        if emit_events:
            self._emit(row)
        return row

    def _end(self, row, error, emit_events):
        ended = self.clock()
        ended_cpu = self.cpu_clock()
        with self._lock:
            _, started, started_cpu = self._active.pop(row["index"])
            outcome = failure_kind(error) if error is not None else (
                "nonzero_exit" if row.get("returncode", 0) != 0 else "completed")
            row.update(status="finished", duration_ns=max(0, ended - started),
                       duration_cpu_ns=max(0, ended_cpu - started_cpu), outcome=outcome)
            if error is not None and "timeout_seconds" in row:
                row["exit_kind"] = outcome if outcome in {"timeout", "os_error"} else "raised"
                row["returncode"] = None
            summary = self._summary.setdefault(row["phase"], dict(calls=0, duration_ns=0, cpu_ns=0, outcomes={}))
            summary["calls"] += 1
            summary["duration_ns"] += row["duration_ns"]
            summary["cpu_ns"] += row["duration_cpu_ns"]
            summary["outcomes"][outcome] = summary["outcomes"].get(outcome, 0) + 1
        if emit_events:
            self._emit(row)

    @contextmanager
    def lock_file(self, handle):
        """Retain native lock ownership and observe its actual final close."""
        try:
            yield handle
        finally:
            with self.phase("lock_close"):
                handle.close()

    def snapshot(self):
        now = self.clock()
        cpu_now = self.cpu_clock()
        with self._lock:
            return self._snapshot(now, cpu_now)

    def _snapshot(self, now, cpu_now):
        return dict(schema=SCHEMA, job=self.job, run_id=self.run_id, started_at=self.started_at,
                    elapsed_ns=max(0, now - self.started_ns),
                    process_cpu_elapsed_ns=max(0, cpu_now - self.started_cpu_ns),
                    phases=deepcopy(list(self._events)),
                    phase_summary=deepcopy(self._summary), open_phases=len(self._active),
                    active_phases=[deepcopy(row) for row, _, _ in self._active.values()],
                    dropped_phase_details=self._dropped, sink_failures=self._sink_failures,
                    phase_times="inclusive_overlap_possible", clock="time.monotonic_ns",
                    cpu_clock="time.process_time_ns", cpu_scope="current_process_inclusive_overlap_possible",
                    excludes="own_runtime_sidecar_publication")

    def finish(self, *, run_exit_kind="returned", job_complete=None):
        if run_exit_kind not in {"returned", "raised"} or job_complete is not None and type(job_complete) is not bool:
            raise ValueError("Invalid runtime completion category")
        now = self.clock()
        cpu_now = self.cpu_clock()
        with self._lock:
            if self._finished is None:
                self._finished = self._snapshot(now, cpu_now)
                self._finished.update(completed_at=datetime.now(UTC).isoformat(),
                                      run_exit_kind=run_exit_kind, job_complete=job_complete)
            return deepcopy(self._finished)
