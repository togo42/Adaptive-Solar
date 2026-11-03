"""Runtime evidence measures real regions and never serializes private errors."""
import json
import subprocess
from types import SimpleNamespace

import pytest

from scripts.runtime_metrics import PhaseRecorder


class Clock:
    def __init__(self):
        self.now = 0

    def __call__(self):
        return self.now

    def advance(self, amount):
        self.now += amount


def test_nested_times_are_inclusive_and_cpu_is_current_process_only():
    wall, cpu = Clock(), Clock()
    recorder = PhaseRecorder("actuals", clock=wall, cpu_clock=cpu)
    with recorder.phase("quality_derive"):
        wall.advance(3)
        cpu.advance(2)
        with recorder.phase("quality_source_scan"):
            wall.advance(7)
            cpu.advance(4)
        wall.advance(5)
        cpu.advance(1)
    result = recorder.finish(job_complete=True)
    assert result["elapsed_ns"] == 15 and result["process_cpu_elapsed_ns"] == 7
    assert result["phase_summary"]["quality_derive"] == {
        "calls": 1, "duration_ns": 15, "cpu_ns": 7, "outcomes": {"completed": 1}}
    assert result["phase_summary"]["quality_source_scan"]["duration_ns"] == 7
    assert result["phase_summary"]["quality_source_scan"]["cpu_ns"] == 4
    assert result["cpu_scope"] == "current_process_inclusive_overlap_possible"
    assert result["open_phases"] == 0
    result["phase_summary"].clear()
    wall.advance(999)
    assert recorder.finish()["elapsed_ns"] == 15
    assert recorder.finish()["phase_summary"]


def test_hot_spans_keep_aggregates_active_evidence_and_late_details():
    wall, cpu, events = Clock(), Clock(), []
    recorder = PhaseRecorder("actuals", clock=wall, cpu_clock=cpu, sink=events.append, max_events=2)
    for _ in range(600):
        with recorder.phase("original_read", emit_events=False):
            wall.advance(2)
            cpu.advance(1)
            active = recorder.snapshot()
    assert active["open_phases"] == 1
    assert active["active_phases"][0]["phase"] == "original_read"
    assert active["active_phases"][0]["duration_ns"] is None
    assert not events and not recorder.snapshot()["phases"]
    for label in ("stats", "result_write", "lock_close"):
        with recorder.phase(label):
            pass
    result = recorder.finish()
    assert result["phase_summary"]["original_read"] == {
        "calls": 600, "duration_ns": 1200, "cpu_ns": 600, "outcomes": {"completed": 600}}
    assert [row["phase"] for row in result["phases"]] == ["result_write", "lock_close"]
    assert result["dropped_phase_details"] == 1 and len(events) == 6


@pytest.mark.parametrize("error,outcome", [
    (subprocess.TimeoutExpired(["private-argv"], 1200, output="private-output"), "timeout"),
    (OSError("private-error"), "os_error"), (ValueError("private-error"), "invalid_data"),
    (KeyError("private-error"), "invalid_data"), (KeyboardInterrupt("private-error"), "interrupted"),
    (RuntimeError("private-error"), "internal_error"),
])
def test_failures_are_sanitized_and_original_exception_is_preserved(error, outcome):
    recorder = PhaseRecorder("actuals")
    with pytest.raises(type(error)) as raised:
        with recorder.phase("child_run", timeout_seconds=1200):
            raise error
    assert raised.value is error
    result = recorder.finish(run_exit_kind="raised")
    assert result["phases"][0]["outcome"] == outcome
    assert result["phases"][0]["returncode"] is None
    assert "private" not in json.dumps(result)


def test_process_return_codes_and_argument_privacy():
    recorder = PhaseRecorder("ha")
    def process(*args, **kwargs):
        assert args == (["private-command"],) and kwargs["env"] == {"private": "secret"}
        return SimpleNamespace(returncode=-9)
    assert recorder.process("child_run", process, ["private-command"], env={"private": "secret"}, timeout=1200).returncode == -9
    row, = recorder.finish()["phases"]
    assert row["exit_kind"] == "exited" and row["returncode"] == -9 and row["outcome"] == "nonzero_exit"
    assert "private" not in json.dumps(row)


def test_unfinished_snapshot_does_not_invent_a_completed_span():
    clock = Clock()
    recorder = PhaseRecorder("actuals", clock=clock)
    span = recorder.phase("quality_source_scan", emit_events=False)
    span.__enter__()
    clock.advance(99)
    result = recorder.finish(run_exit_kind="raised")
    assert result["elapsed_ns"] == 99 and result["open_phases"] == 1
    assert result["active_phases"][0]["duration_ns"] is None
    assert not result["phase_summary"]
    span.__exit__(None, None, None)


def test_sink_failure_does_not_change_observed_work_and_close_is_measured():
    clock = Clock()
    def sink(_event):
        raise OSError("private-sink-error")
    recorder = PhaseRecorder("status", clock=clock, sink=sink)
    handle = SimpleNamespace(close=lambda: clock.advance(7))
    with recorder.lock_file(handle):
        clock.advance(3)
    result = recorder.finish()
    assert result["elapsed_ns"] == 10 and result["phase_summary"]["lock_close"]["duration_ns"] == 7
    assert result["sink_failures"] == 2 and "private" not in json.dumps(result)


@pytest.mark.parametrize("kwargs", [{"phase": "private-label"}, {"phase": "stats", "ordinal": True},
    {"phase": "stats", "timeout_seconds": float("nan")}, {"phase": "stats", "timeout_seconds": -1}])
def test_phase_rejects_unbounded_or_unapproved_fields(kwargs):
    with pytest.raises(ValueError):
        PhaseRecorder("status").phase(**kwargs)
