"""Opt-in, pinned in-memory phase tracing for an existing archive release.

No target source is written. Bootstrap stops tracing before the native main
call, then replaces function code with reversible AST instrumentation. Reader
and projection bodies retain their own frame and original exception handling.
Only fixed phase labels and process counters enter the separate sidecars.
"""

from __future__ import annotations

import ast
import atexit
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import types

from scripts.runtime_metrics import PhaseRecorder

ENVIRONMENT = "ADAPTIVE_SOLAR_RUNTIME_TRACE"
SCHEMA = "adaptive-solar-pinned-runtime-trace-v1"
PREFIX = "_asrt_"
ENTRYPOINTS = frozenset({"scripts/archive_host.py", "scripts/archive_observations.py", "scripts/archive.py"})
SOURCE_FILES = frozenset(
    {
        *ENTRYPOINTS,
        "scripts/continuous_quality.py",
        "scripts/capture_actuals.py",
        "scripts/actual_quality_io.py",
        "scripts/quality_capture.py",
        "custom_components/adaptive_solar/core/archive.py",
        "custom_components/adaptive_solar/core/actual_quality.py",
    }
)
FUNCTION_PHASES = {
    "scripts.continuous_quality": {"derive": ("quality_derive", True)},
    "scripts.capture_actuals": {
        "capture_actuals": ("recorder_capture", True),
        "normalize_capture": ("normalization", False),
    },
    "scripts.quality_capture": {"compact_capture": ("normalization", True)},
    "scripts.archive_observations": {"append_capture": ("archive_append", True)},
    "scripts.archive": {"collect": ("archive_collect", True)},
    "custom_components.adaptive_solar.core.actual_quality": {"build_quality": ("quality_build", True)},
    "custom_components.adaptive_solar.core.archive": {
        "ArchiveStore.__init__": ("store_init", True),
        "ArchiveStore._reconcile": ("store_reconcile", True),
        "ArchiveStore._read_original": ("original_read", False),
        "ArchiveStore.resolve_events": ("payload_resolve", False),
        "ArchiveJournal.__init__": ("store_init", True),
        "ArchiveJournal.append_many": ("archive_append", True),
    },
}


def _call(name, *args, **kwargs):
    return ast.Call(
        func=ast.Attribute(value=ast.Name(id=PREFIX + "recorder", ctx=ast.Load()), attr=name, ctx=ast.Load()),
        args=list(args),
        keywords=[ast.keyword(arg=k, value=v) for k, v in kwargs.items()],
    )


def _phase(body, label, *, emit=True, timeout=None, process_result=None):
    keywords = {"emit_events": ast.Constant(emit)}
    if timeout is not None:
        keywords["timeout_seconds"] = copy.deepcopy(timeout)
    after = []
    if process_result is not None:
        after = [
            ast.Expr(
                ast.Call(
                    ast.Attribute(ast.Name(PREFIX + "span", ast.Load()), "exited", ast.Load()),
                    [ast.Attribute(ast.Name(process_result, ast.Load()), "returncode", ast.Load())],
                    [],
                )
            )
        ]
    return ast.With(
        items=[
            ast.withitem(
                _call("phase", ast.Constant(label), **keywords),
                ast.Name(PREFIX + "span", ast.Store()) if process_result else None,
            )
        ],
        body=[*body, *after],
    )


def _is_call(node, module, name):
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == module
        and node.func.attr == name
    )


class _Instrument(ast.NodeTransformer):
    def __init__(self, *, host=False, derive=False, observations=False):
        self.host, self.derive, self.observations = host, derive, observations

    def visit_FunctionDef(self, node):
        node = self.generic_visit(node)
        if self.derive and node.name == "project":
            node.body = [_phase(node.body, "quality_config_projection", emit=False)]
        return node

    def visit_For(self, node):
        node = self.generic_visit(node)
        if self.derive and isinstance(node.target, ast.Name) and node.target.id == "source":
            node.body = [_phase(node.body, "quality_source_scan")]
        return node

    def visit_Expr(self, node):
        node = self.generic_visit(node)
        if self.host and _is_call(node.value, "fcntl", "flock"):
            return _phase([node], "lock_wait")
        return node

    def visit_Assign(self, node):
        node = self.generic_visit(node)
        if self.host and isinstance(node.value, ast.Call):
            if isinstance(node.value.func, ast.Name) and node.value.func.id == "capacity":
                return _phase([node], "capacity")
            if _is_call(node.value, "subprocess", "run"):
                if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                    raise ValueError("Unsupported native process assignment")
                result = node.targets[0].id
                if result not in {"result", "stats"}:
                    raise ValueError("Unsupported native process result")
                timeout = next((k.value for k in node.value.keywords if k.arg == "timeout"), None)
                return _phase(
                    [node], "stats" if result == "stats" else "child_run", timeout=timeout, process_result=result
                )
        if (
            self.observations
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "recovered"
            and isinstance(node.value, ast.Await)
        ):
            return _phase([node], "recovery")
        return node

    def visit_With(self, node):
        node = self.generic_visit(node)
        if (
            self.host
            and len(node.items) == 1
            and isinstance(node.items[0].optional_vars, ast.Name)
            and node.items[0].optional_vars.id == "lock"
        ):
            item = node.items[0]
            opening = _phase([ast.Assign([ast.Name(PREFIX + "lock", ast.Store())], item.context_expr)], "lock_open")
            item.context_expr = _call("lock_file", ast.Name(PREFIX + "lock", ast.Load()))
            return [opening, node]
        return node


class _Strip(ast.NodeTransformer):
    """Remove only the instrumentation grammar and reconstruct native AST."""

    def _body(self, body):
        result = []
        i = 0
        while i < len(body):
            row = body[i]
            if (
                isinstance(row, ast.With)
                and len(row.items) == 1
                and _is_call(row.items[0].context_expr, PREFIX + "recorder", "phase")
            ):
                label = row.items[0].context_expr.args[0].value
                if label == "lock_open":
                    opening = row.body[0]
                    following = body[i + 1]
                    if (
                        not isinstance(opening, ast.Assign)
                        or not isinstance(following, ast.With)
                        or not _is_call(following.items[0].context_expr, PREFIX + "recorder", "lock_file")
                    ):
                        raise ValueError("Invalid trace lock grammar")
                    following.items[0].context_expr = opening.value
                    result.append(self.visit(following))
                    i += 2
                    continue
                native = row.body
                if row.items[0].optional_vars is not None:
                    if not isinstance(native[-1], ast.Expr) or not _is_call(
                        native[-1].value, PREFIX + "span", "exited"
                    ):
                        raise ValueError("Invalid trace process grammar")
                    native = native[:-1]
                result.extend(self._body(native))
            else:
                result.append(self.visit(row))
            i += 1
        return result

    def generic_visit(self, node):
        for field, value in ast.iter_fields(node):
            if isinstance(value, list) and value and all(isinstance(v, ast.stmt) for v in value):
                setattr(node, field, self._body(value))
            elif isinstance(value, list):
                setattr(node, field, [self.visit(v) if isinstance(v, ast.AST) else v for v in value])
            elif isinstance(value, ast.AST):
                setattr(node, field, self.visit(value))
        return node


def prepare_function(function, *, phase=None, emit=True, host=False, derive=False, observations=False):
    """Compile without mutation and prove removal yields the entire native AST."""
    source = Path(function.__code__.co_filename)
    tree = ast.parse(source.read_text(), filename=str(source))
    name_parts = function.__qualname__.split(".")
    nodes = tree.body
    for name in name_parts:
        if name == "<locals>":
            raise ValueError("Nested functions must be instrumented with their enclosing native function")
        found = next(
            (
                n
                for n in nodes
                if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name
            ),
            None,
        )
        if found is None:
            raise ValueError("Native function not found")
        nodes = found.body
    original = copy.deepcopy(found)
    if any(isinstance(n, ast.Name) and n.id.startswith(PREFIX) for n in ast.walk(original)):
        raise ValueError("Native trace namespace collision")
    patched = _Instrument(host=host, derive=derive, observations=observations).visit(copy.deepcopy(original))
    if phase:
        patched.body = [_phase(patched.body, phase, emit=emit)]
    stripped = _Strip().visit(copy.deepcopy(patched))
    if ast.dump(original, include_attributes=False) != ast.dump(stripped, include_attributes=False):
        raise ValueError("Native AST changed beyond instrumentation")
    # Do not execute decorators, defaults or annotations for a second time.
    patched.decorator_list = []
    module = ast.Module(body=[patched], type_ignores=[])
    ast.fix_missing_locations(module)
    code = compile(module, str(source), "exec")
    replacement = next(c for c in code.co_consts if isinstance(c, types.CodeType) and c.co_name == function.__name__)
    if replacement.co_freevars != function.__code__.co_freevars:
        raise ValueError("Native closure changed")
    replacement = replacement.replace(co_qualname=function.__code__.co_qualname)
    original_ast = hashlib.sha256(ast.dump(original, include_attributes=False).encode()).hexdigest()
    return replacement, {
        "function": function.__qualname__,
        "native_ast_sha256": original_ast,
        "stripped_ast_sha256": original_ast,
        "same_frame": True,
    }


def instrument_function(function, recorder, **options):
    """Apply one previously reversible code change (sessions use a transaction)."""
    replacement, proof = prepare_function(function, **options)
    function.__globals__[PREFIX + "recorder"] = recorder
    function.__code__ = replacement
    return proof


def load_manifest(path, expected_sha256):
    """Validate explicit roots, complete fixed source pins and sidecar boundary."""
    path = Path(path)
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("Trace manifest must be an absolute regular file")
    raw = path.read_bytes()
    if (
        not isinstance(expected_sha256, str)
        or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
        or hashlib.sha256(raw).hexdigest() != expected_sha256
    ):
        raise ValueError("Trace manifest pin mismatch")
    data = json.loads(raw)
    if set(data) != {
        "schema",
        "run_id",
        "source_root",
        "telemetry_dir",
        "sources",
        "helper_sources",
        "native_sitecustomize",
    }:
        raise ValueError("Invalid trace manifest fields")
    if data["schema"] != SCHEMA or not re.fullmatch(r"[0-9a-f-]{36}", data["run_id"]):
        raise ValueError("Invalid trace manifest")
    root = Path(data["source_root"])
    output = Path(data["telemetry_dir"])
    if (
        not root.is_absolute()
        or root.resolve() != root
        or not output.is_absolute()
        or output.is_symlink()
        or output.resolve() != output
        or not output.is_dir()
        or output.is_relative_to(root)
    ):
        raise ValueError("Trace roots must be resolved and separate")
    if set(data["sources"]) != SOURCE_FILES:
        raise ValueError("Incomplete native trace source allowlist")
    for rel, digest in data["sources"].items():
        target = root / rel
        if (
            not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or not target.is_file()
            or not target.resolve().is_relative_to(root)
            or hashlib.sha256(target.read_bytes()).hexdigest() != digest
        ):
            raise ValueError("Native trace source pin mismatch")
    expected_helpers = {"archive_runtime_trace.py", "runtime_metrics.py", "sitecustomize.py"}
    if set(data["helper_sources"]) != expected_helpers:
        raise ValueError("Incomplete trace helper pins")
    helper_root = Path(__file__).resolve().parent
    for name, digest in data["helper_sources"].items():
        target = helper_root / name if name != "sitecustomize.py" else helper_root.parent / "bootstrap" / name
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError("Trace helper pin mismatch")
    native = data["native_sitecustomize"]
    loaded = sys.modules.get("sitecustomize")
    if native is not None:
        if not isinstance(native, dict) or set(native) != {"path", "sha256"}:
            raise ValueError("Invalid native bootstrap pin")
        path = Path(native["path"])
        if (
            not path.is_absolute()
            or hashlib.sha256(path.read_bytes()).hexdigest() != native["sha256"]
            or loaded is None
            or Path(getattr(loaded, "__file__", "")).absolute() != path
            or loaded.__spec__.name != "sitecustomize"
        ):
            raise ValueError("Native bootstrap identity or source drift")
    return data


class TraceSession:
    """Rate-limited atomic liveness survives a child timeout without finishing."""

    def __init__(self, manifest, role):
        self.manifest, self.role = manifest, role
        self.recorder = PhaseRecorder(role, run_id=manifest["run_id"])
        self.stop = threading.Event()
        self.path = Path(manifest["telemetry_dir"]) / f"{role}-{os.getpid()}.json"
        self.patches = []
        self.publish_failures = 0
        self.thread = None

    def publish(self, *, final=False):
        value = self.recorder.finish() if final else self.recorder.snapshot()
        value.update(
            trace_schema=SCHEMA,
            pid=os.getpid(),
            parent_pid=os.getppid(),
            process_status="finished" if final else "running",
            source_sha256=self.manifest["sources"],
            native_sitecustomize=self.manifest.get("native_sitecustomize"),
            patches=self.patches,
            publication_failures=self.publish_failures,
            exit_status_scope="Native exit status is observed separately by the parent or systemd",
        )
        name = None
        try:
            fd, name = tempfile.mkstemp(prefix=".trace-", dir=self.path.parent)
            with os.fdopen(fd, "w") as handle:
                json.dump(value, handle, sort_keys=True, allow_nan=False)
                handle.write("\n")
            os.replace(name, self.path)
        except OSError:
            self.publish_failures += 1
        finally:
            if name is not None:
                try:
                    Path(name).unlink(missing_ok=True)
                except OSError:
                    self.publish_failures += 1

    def start(self):
        self.publish()

        def loop():
            while not self.stop.wait(5):
                self.publish()

        thread = threading.Thread(target=loop, name="archive-runtime-status", daemon=True)
        self.thread = thread
        thread.start()

        def finish():
            self.stop.set()
            thread.join(timeout=1)
            self.publish(final=True)

        atexit.register(finish)

    def install(self, namespace, entrypoint):
        prepared = []

        def prepare(function, **options):
            replacement, proof = prepare_function(function, **options)
            prepared.append((function, replacement, proof))

        modules = dict(sys.modules)
        modules[
            {
                "scripts/archive_host.py": "scripts.archive_host",
                "scripts/archive_observations.py": "scripts.archive_observations",
                "scripts/archive.py": "scripts.archive",
            }[entrypoint]
        ] = types.SimpleNamespace(**namespace)
        for module_name, definitions in FUNCTION_PHASES.items():
            module = modules.get(module_name)
            if module is None:
                continue
            for qualified, (phase, emit) in definitions.items():
                owner = module
                for part in qualified.split(".")[:-1]:
                    owner = getattr(owner, part)
                function = getattr(owner, qualified.split(".")[-1])
                relative = module_name.replace(".", "/") + ".py"
                if Path(function.__code__.co_filename).resolve() != Path(self.manifest["source_root"]) / relative:
                    raise ValueError("Native function origin mismatch")
                prepare(function, phase=phase, emit=emit, derive=module_name == "scripts.continuous_quality")
        if entrypoint == "scripts/archive_host.py":
            prepare(namespace["run"], host=True)
            prepare(namespace["write_status"], phase="result_write")
            prepare(namespace["commands"], phase="job_prepare")
        if entrypoint == "scripts/archive_observations.py":
            prepare(namespace["archive_observations"], observations=True)
        functions = {function: function.__code__ for function, _, _ in prepared}
        missing = object()
        globals_before = {
            id(function.__globals__): (function.__globals__, function.__globals__.get(PREFIX + "recorder", missing))
            for function, _, _ in prepared
        }
        try:
            for function, replacement, proof in prepared:
                function.__globals__[PREFIX + "recorder"] = self.recorder
                function.__code__ = replacement
                self.patches.append(proof)
            self.start()
        except BaseException:
            self.stop.set()
            if self.thread is not None and self.thread.is_alive():
                self.thread.join(timeout=1)
            for function, native_code in functions.items():
                function.__code__ = native_code
            for namespace, value in globals_before.values():
                if value is missing:
                    namespace.pop(PREFIX + "recorder", None)
                else:
                    namespace[PREFIX + "recorder"] = value
            self.patches = []
            raise


def bootstrap(manifest_path, expected_sha256):
    """Observe startup only; never import or execute a native entrypoint twice."""
    manifest = load_manifest(manifest_path, expected_sha256)
    script = Path(sys.argv[0]).resolve()
    root = Path(manifest["source_root"])
    try:
        entrypoint = str(script.relative_to(root))
    except ValueError:
        return None
    if entrypoint not in ENTRYPOINTS:
        return None
    tree = ast.parse(script.read_text(), filename=str(script))
    guards = [
        n
        for n in tree.body
        if isinstance(n, ast.If)
        and isinstance(n.test, ast.Compare)
        and ast.dump(n.test, include_attributes=False)
        == ast.dump(ast.parse("__name__ == '__main__'", mode="eval").body, include_attributes=False)
    ]
    if len(guards) != 1 or guards[0] is not tree.body[-1]:
        raise ValueError("Native final main guard required")
    if sys.gettrace() is not None:
        raise ValueError("Existing startup trace must not be replaced")
    role = {
        "scripts/archive_host.py": "host",
        "scripts/archive_observations.py": "observations",
        "scripts/archive.py": "archive",
    }[entrypoint]
    session = TraceSession(manifest, role)
    filenames = {str(script), str(Path(sys.argv[0]).absolute())}

    def startup(frame, event, _arg):
        target = frame.f_code.co_filename in filenames and frame.f_code.co_name == "<module>"
        if not target:
            return None
        if event == "line" and frame.f_lineno == guards[0].lineno:
            sys.settrace(None)
            frame.f_trace = None
            try:
                session.install(frame.f_globals, entrypoint)
            except Exception:
                os.write(2, b"Archive runtime telemetry instrumentation failed; native execution continues.\n")
            return None
        return startup

    sys.settrace(startup)
    return session
