"""Pinned opt-in runtime tracing preserves native frames, gates and errors."""

import asyncio
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

from scripts import archive_runtime_trace as trace
from scripts.runtime_metrics import PhaseRecorder
from custom_components.adaptive_solar.core import archive

ROOT = Path(__file__).resolve().parents[1]


def module_file(tmp_path, text):
    path = tmp_path / "native.py"
    path.write_text(text)
    spec = importlib.util.spec_from_file_location("trace_test_native", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_same_frame_deep_json_parity_and_defaults(tmp_path):
    module = module_file(
        tmp_path,
        """import json
import sys
marker = object()
def read(raw, value=marker):
    try:
        decoded = json.loads(raw)
        return (type(decoded).__name__, value is marker)
    except (ValueError, RecursionError):
        return ("rejected", value is marker)
""",
    )
    samples = ["[" * n + "0" + "]" * n for n in range(850, 1101, 10)]

    def decisions():
        return [module.read(raw) for raw in samples]

    before = decisions()
    recorder = PhaseRecorder("test")
    identity, defaults = module.read, module.read.__defaults__
    proof = trace.instrument_function(module.read, recorder, phase="original_read", emit=False)
    assert decisions() == before
    assert module.read is identity and module.read.__defaults__ is defaults
    assert proof["same_frame"] and proof["native_ast_sha256"] == proof["stripped_ast_sha256"]
    assert recorder.snapshot()["phase_summary"]["original_read"]["calls"] == len(samples)
    assert recorder.snapshot()["phases"] == []


def test_actual_archive_reader_deep_acceptance_is_unchanged(tmp_path, monkeypatch):
    cases = []
    limit = sys.getrecursionlimit()
    try:
        sys.setrecursionlimit(5000)
        for depth in (600, 1100):
            payload = 0
            for _ in range(depth):
                payload = [payload]
            generation, stamp = "00000000-0000-0000-0000-000000000001", "2026-01-01T00:00:00+00:00"
            event = {
                "schema": 1,
                "generation": generation,
                "sequence": 1,
                "event_id": "synthetic-event",
                "kind": "diagnostic",
                "received_at": stamp,
                "payload": {"deep": payload},
            }
            event["sha256"] = hashlib.sha256(archive.canonical_bytes(event)).hexdigest()
            wrapper = {
                "schema": 1,
                "source": "synthetic-source",
                "ingest_order": 1,
                "stored_at": stamp,
                "archive_started_at": stamp,
                "page": {
                    "schema": 1,
                    "generation": generation,
                    "oldest_sequence": 1,
                    "requested_cursor": None,
                    "next_cursor": generation + ":1",
                    "events": [event],
                    "gap": None,
                },
            }
            raw = json.dumps(wrapper, separators=(",", ":")).encode()
            path = tmp_path / (hashlib.sha256(raw).hexdigest() + ".json.gz")
            path.write_bytes(gzip.compress(raw, mtime=0))
            cases.append(path)
    finally:
        sys.setrecursionlimit(limit)
    reader = object.__new__(archive.ArchiveStore)

    def decisions():
        results = []
        for path in cases:
            try:
                value = reader._read_original(path)
                results.append(("accepted", value["page"]["events"][0]["sha256"]))
            except Exception as error:
                results.append(("rejected", type(error).__name__, str(error)))
        return results

    before = decisions()
    function = archive.ArchiveStore._read_original
    monkeypatch.setattr(function, "__code__", function.__code__)
    monkeypatch.setitem(function.__globals__, trace.PREFIX + "recorder", None)
    trace.instrument_function(function, PhaseRecorder("test"), phase="original_read", emit=False)
    assert decisions() == before
    assert {row[0] for row in before} == {"accepted", "rejected"}


@pytest.mark.parametrize(
    "error,outcome",
    [(subprocess.TimeoutExpired("private-secret", 1200), "timeout"), (OSError("private-secret"), "os_error")],
)
def test_host_callsites_preserve_catches_and_record_distinct_failure(tmp_path, error, outcome):
    module = module_file(
        tmp_path,
        """import subprocess
import fcntl
def capacity(path, config):
    return {"allowed": True}
def run(path):
    with path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        limits = capacity(path, {})
        try:
            result = subprocess.run(["private-secret"], timeout=1200)
        except (OSError, subprocess.TimeoutExpired):
            return "native-caught"
        return result.returncode, limits
""",
    )
    module.subprocess = SimpleNamespace(
        run=lambda *a, **k: (_ for _ in ()).throw(error), TimeoutExpired=subprocess.TimeoutExpired
    )
    recorder = PhaseRecorder("host")
    trace.instrument_function(module.run, recorder, host=True)
    assert module.run(tmp_path / "lock") == "native-caught"
    snapshot = recorder.finish()
    assert snapshot["open_phases"] == 0
    assert snapshot["phase_summary"]["child_run"]["outcomes"] == {outcome: 1}
    assert snapshot["phase_summary"]["lock_close"]["calls"] == 1
    assert snapshot["phase_summary"]["lock_wait"]["calls"] == 1
    assert snapshot["phase_summary"]["capacity"]["calls"] == 1
    assert "private-secret" not in json.dumps(snapshot)


def test_process_returncode_and_async_result_remain_native(tmp_path):
    module = module_file(
        tmp_path,
        """import subprocess
def run():
    result = subprocess.run(["secret"], timeout=1200)
    stats = subprocess.run(["secret"], timeout=300)
    return result, stats
async def capture_actuals(value):
    return value
""",
    )
    expected = [SimpleNamespace(returncode=1), SimpleNamespace(returncode=0)]
    values = iter(expected)
    module.subprocess = SimpleNamespace(run=lambda *a, **k: next(values))
    recorder = PhaseRecorder("test")
    trace.instrument_function(module.run, recorder, host=True)
    trace.instrument_function(module.capture_actuals, recorder, phase="recorder_capture")
    assert module.run() == tuple(expected)
    marker = object()
    assert asyncio.run(module.capture_actuals(marker)) is marker
    phases = recorder.snapshot()["phases"]
    assert phases[0]["returncode"] == 1 and phases[0]["outcome"] == "nonzero_exit"
    assert phases[0]["timeout_seconds"] == 1200
    assert phases[1]["returncode"] == 0 and phases[1]["timeout_seconds"] == 300


def test_derive_projects_nested_closure_in_native_frame(tmp_path):
    module = module_file(
        tmp_path,
        """def derive(rows):
    result = []
    def project(value):
        result.append(value)
    for source in rows:
        project(source)
    return result
""",
    )
    recorder = PhaseRecorder("test")
    trace.instrument_function(module.derive, recorder, phase="quality_derive", derive=True)
    assert module.derive([1, 2]) == [1, 2]
    summary = recorder.snapshot()["phase_summary"]
    assert summary["quality_source_scan"]["calls"] == 2
    assert summary["quality_config_projection"]["calls"] == 2


def installation(tmp_path):
    source = tmp_path / "release"
    output = tmp_path / "telemetry"
    helper = tmp_path / "helper"
    output.mkdir()
    for rel in trace.SOURCE_FILES:
        path = source / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Public synthetic native source\n")
    script = source / "scripts/archive_host.py"
    script.write_text("""import json
import sys
def commands():
    return ["private-secret"]
def write_status():
    return True
def run():
    return commands(), write_status()
def main():
    print(json.dumps({"result": run(), "trace_disabled": sys.gettrace() is None}))
if __name__ == "__main__":
    main()
""")
    for rel, origin in {
        "scripts/archive_runtime_trace.py": ROOT / "scripts/archive_runtime_trace.py",
        "scripts/runtime_metrics.py": ROOT / "scripts/runtime_metrics.py",
        "bootstrap/sitecustomize.py": ROOT / "tools/archive_runtime_trace/sitecustomize.py",
    }.items():
        path = helper / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(origin, path)
    manifest = {
        "schema": trace.SCHEMA,
        "run_id": "12345678-1234-1234-1234-123456789abc",
        "source_root": str(source),
        "telemetry_dir": str(output),
        "sources": {rel: hashlib.sha256((source / rel).read_bytes()).hexdigest() for rel in trace.SOURCE_FILES},
        "helper_sources": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in helper.rglob("*.py")},
        "native_sitecustomize": {
                "path": str(Path(sys.modules["sitecustomize"].__file__).absolute()),
            "sha256": hashlib.sha256(Path(sys.modules["sitecustomize"].__file__).read_bytes()).hexdigest(),
        }
        if "sitecustomize" in sys.modules
        else None,
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest, sort_keys=True))
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(map(str, [helper / "bootstrap", helper, source])),
        trace.ENVIRONMENT: str(path),
        trace.ENVIRONMENT + "_SHA256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    return source, output, helper, path, env


def test_sitecustomize_pinned_symlink_entrypoint_and_native_output(tmp_path):
    source, output, helper, manifest, env = installation(tmp_path)
    link = tmp_path / "current"
    link.symlink_to(source, target_is_directory=True)
    before = {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}
    run = subprocess.run(
        [sys.executable, "-B", str(link / "scripts/archive_host.py")],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == {"result": [["private-secret"], True], "trace_disabled": True}
    files = list(output.glob("host-*.json"))
    assert len(files) == 1
    value = json.loads(files[0].read_text())
    assert value["process_status"] == "finished" and value["open_phases"] == 0
    assert value["run_id"] == "12345678-1234-1234-1234-123456789abc"
    assert value["phase_summary"]["result_write"]["calls"] == 1
    assert all(row["same_frame"] for row in value["patches"])
    assert "private-secret" not in files[0].read_text()
    assert all(p.read_bytes() == raw for p, raw in before.items())
    assert not list(helper.rglob("*.pyc")) and not list(source.rglob("*.pyc"))


@pytest.mark.parametrize("mutation", ["manifest", "native", "helper"])
def test_opted_in_bad_pin_warns_and_preserves_native_execution(tmp_path, mutation):
    source, output, helper, manifest, env = installation(tmp_path)
    target = {
        "manifest": manifest,
        "native": source / "scripts/archive.py",
        "helper": helper / "scripts/runtime_metrics.py",
    }[mutation]
    target.write_text(target.read_text() + "\n# changed\n")
    run = subprocess.run(
        [sys.executable, "-B", str(source / "scripts/archive_host.py")],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert run.returncode == 0 and json.loads(run.stdout)["result"] == [["private-secret"], True]
    assert run.stderr == "Archive runtime telemetry bootstrap failed; native execution continues.\n"
    assert not list(output.iterdir())


def test_sitecustomize_without_opt_in_is_inert(tmp_path):
    source, output, _helper, _manifest, env = installation(tmp_path)
    env.pop(trace.ENVIRONMENT)
    run = subprocess.run(
        [sys.executable, "-B", str(source / "scripts/archive_host.py")],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert run.returncode == 0 and not list(output.iterdir())


def test_partial_installation_failure_restores_code_and_global_bindings(tmp_path, monkeypatch):
    module = module_file(
        tmp_path,
        """def commands():
    return "native-commands"
def write_status():
    return "native-status"
def run():
    return commands(), write_status()
""",
    )
    session = trace.TraceSession(
        {"run_id": "12345678-1234-1234-1234-123456789abc", "telemetry_dir": str(tmp_path)}, "host"
    )
    original = {name: getattr(module, name).__code__ for name in ("run", "commands", "write_status")}
    marker = object()
    module.__dict__[trace.PREFIX + "recorder"] = marker

    def fail_after_mutation():
        assert module.run.__code__ is not original["run"]
        raise OSError("private-secret")

    monkeypatch.setattr(session, "start", fail_after_mutation)
    monkeypatch.setattr(trace, "FUNCTION_PHASES", {})
    with pytest.raises(OSError):
        session.install(vars(module), "scripts/archive_host.py")
    assert all(getattr(module, name).__code__ is code for name, code in original.items())
    assert module.__dict__[trace.PREFIX + "recorder"] is marker
    assert module.run() == ("native-commands", "native-status")
    assert session.patches == []


def test_native_sitecustomize_identity_and_guard_run_before_telemetry(tmp_path):
    source, output, helper, manifest, env = installation(tmp_path)
    native = tmp_path / "native-hook"
    native.mkdir()
    path = native / "sitecustomize.py"
    path.write_text("""import sys
identity_preserved = sys.modules[__name__].__dict__ is globals()
class NativeGuard:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "synthetic_ha_guard":
            raise ImportError("native guard remains active")
sys.meta_path.insert(0, NativeGuard())
""")
    script = source / "scripts/archive_host.py"
    text = script.read_text().replace(
        'print(json.dumps({"result": run(), "trace_disabled": sys.gettrace() is None}))',
        """import sitecustomize
    assert sitecustomize.identity_preserved
    assert sitecustomize.__spec__.name == "sitecustomize"
    assert sitecustomize.__file__ == """
        + repr(str(path))
        + """
    try:
        import synthetic_ha_guard
    except ImportError:
        guarded = True
    else:
        guarded = False
    print(json.dumps({"guarded": guarded, "trace_disabled": sys.gettrace() is None}))""",
    )
    script.write_text(text)
    value = json.loads(manifest.read_text())
    value["sources"]["scripts/archive_host.py"] = hashlib.sha256(script.read_bytes()).hexdigest()
    value["native_sitecustomize"] = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    manifest.write_text(json.dumps(value, sort_keys=True))
    env[trace.ENVIRONMENT + "_SHA256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    env["PYTHONPATH"] += os.pathsep + str(native)
    run = subprocess.run([sys.executable, "-B", str(script)], env=env, capture_output=True, text=True, timeout=20)
    assert run.returncode == 0 and not run.stderr, run.stderr
    assert json.loads(run.stdout) == {"guarded": True, "trace_disabled": True}
    assert len(list(output.glob("*.json"))) == 1


def test_native_bootstrap_exception_keeps_native_handling(tmp_path):
    source, output, helper, manifest, env = installation(tmp_path)
    native = tmp_path / "native-hook"
    native.mkdir()
    (native / "sitecustomize.py").write_text('raise ValueError("synthetic native bootstrap failure")\n')
    env["PYTHONPATH"] += os.pathsep + str(native)
    run = subprocess.run(
        [sys.executable, "-B", str(source / "scripts/archive_host.py")],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert run.returncode == 0 and json.loads(run.stdout)["result"] == [["private-secret"], True]
    assert "synthetic native bootstrap failure" in run.stderr
    assert "telemetry bootstrap failed" not in run.stderr
    assert not list(output.iterdir())
