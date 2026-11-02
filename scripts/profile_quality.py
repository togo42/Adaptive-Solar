"""Measure a frozen local quality derivation against explicitly pinned sources.

No HA/network access, archive initialization, writer locks or SQLite writes.
Real decision clocks remain unchanged. Phase times are inclusive and overlap.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, ExitStack
import cProfile
from datetime import UTC, datetime
import functools
import gzip
import hashlib
import importlib
from importlib.abc import MetaPathFinder
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import platform
import pstats
import resource
import sqlite3
import statistics
import subprocess
import sys
import time
from unittest.mock import patch

MIB = 1024 * 1024
GIB = 1024 * MIB


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(MIB):
            digest.update(chunk)
    return digest.hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False, ensure_ascii=False).encode()).hexdigest()


def write_json(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


@contextmanager
def readonly_db(archive):
    uri = (archive / "index.sqlite3").as_uri() + "?mode=ro&immutable=1"
    connection = sqlite3.connect(uri)
    try:
        connection.execute("PRAGMA query_only=ON")
        yield connection
    finally:
        connection.close()


def original_digest(path, archive):
    """Accept only the native flat and hash-prefix original layouts."""
    relative = path.relative_to(archive / "originals")
    value = path.name.removesuffix(".json.gz")
    if (len(value) != 64 or any(char not in "0123456789abcdef" for char in value)
            or len(relative.parts) not in (1, 2)
            or len(relative.parts) == 2 and relative.parts[0] != value[:2]):
        raise ValueError("Unsupported original hash or layout")
    return value


def inventories(args):
    """Hash every frozen file, with hard size/count limits before expensive work."""
    archive, source = args.archive.resolve(), args.source_root.resolve()
    if args.archive.is_symlink() or args.source_root.is_symlink():
        raise ValueError("Frozen roots must not be symlinks")
    for suffix in ("-wal", "-shm", "-journal"):
        if (archive / ("index.sqlite3" + suffix)).exists():
            raise ValueError("Frozen index must have no SQLite sidecars")
    if not (archive / "index.sqlite3").is_file():
        raise ValueError("Existing frozen archive index required")
    files = []
    for path in archive.rglob("*"):
        if path.is_symlink():
            raise ValueError("Frozen archive must not contain symlinks")
        if path.is_dir() and path.is_relative_to(archive / "originals") and path != archive / "originals":
            relative = path.relative_to(archive / "originals")
            if (len(relative.parts) != 1 or len(path.name) != 2
                    or any(char not in "0123456789abcdef" for char in path.name)):
                raise ValueError("Unsupported original directory")
        if path.is_file():
            files.append(path)
        if len(files) > args.max_batches + 32:
            raise ValueError("Archive file count exceeds budget")
    originals = [p for p in files if p.name.endswith(".json.gz")]
    if not originals or len(originals) > args.max_batches:
        raise ValueError("Archive batch count exceeds budget")
    original_hashes = {original_digest(path, archive) for path in originals}
    size = sum(p.stat().st_size for p in originals)
    if size > args.max_archive_bytes or sum(p.stat().st_size for p in files) > 2 * args.max_archive_bytes:
        raise ValueError("Archive byte count exceeds budget")
    decompressed = 0
    for path in originals:
        with path.open("rb") as stream:
            stream.seek(-4, os.SEEK_END)
            decompressed += int.from_bytes(stream.read(4), "little")
    if decompressed > args.max_decompressed_bytes:
        raise ValueError("Original gzip ISIZE inventory exceeds budget")
    with readonly_db(archive) as conn:
        events = conn.execute("SELECT count(*) FROM events").fetchone()[0]
        indexed_hashes = {row[0] for row in conn.execute("SELECT hash FROM batches")}
        indexed_batches = len(indexed_hashes)
        if events > args.max_events or indexed_batches > args.max_batches:
            raise ValueError("Index size exceeds budget")
        if indexed_hashes != original_hashes:
            raise ValueError("Frozen index and original hash sets differ; require a reconciled snapshot")
    for path in (args.raw, args.bindings):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 128 * MIB:
            raise ValueError("Frozen JSON input is missing, aliased or oversized")
    source_files = []
    for path in source.iterdir():
        if path.is_symlink() or path.name == "__pycache__" or path.suffix in {".pyc", ".pyo"}:
            raise ValueError("Pinned source root must have no symlinks or bytecode caches")
        if path.is_file() and path.suffix in {".py", ".json"}:
            source_files.append(path)
    for relative in ("custom_components", "scripts"):
        for path in (source / relative).rglob("*"):
            if path.is_symlink():
                raise ValueError("Pinned sources must not contain symlinks")
            if path.name == "__pycache__" or path.suffix in {".pyc", ".pyo"}:
                raise ValueError("Pinned sources must be source-only, without bytecode caches")
            if path.is_file() and path.suffix in {".py", ".json"}:
                source_files.append(path)
    if not source_files or len(source_files) > 2000 or sum(p.stat().st_size for p in source_files) > 128 * MIB:
        raise ValueError("Pinned public source inventory exceeds budget")
    return {"archive": {str(p.relative_to(archive)): file_hash(p) for p in sorted(files)},
            "sources": {str(p.relative_to(source)): file_hash(p) for p in sorted(source_files)},
            "raw_sha256": file_hash(args.raw), "bindings_sha256": file_hash(args.bindings),
            "batches": len(originals), "indexed_batches": indexed_batches, "indexed_events": events,
            "compressed_original_bytes": size, "archive_file_bytes": sum(p.stat().st_size for p in files),
            "gzip_isize_bytes": decompressed,
            "gzip_isize_note": "Resource inventory only; native original reader still checks every consumed original"}


class BlockHA(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "homeassistant" or fullname.startswith("homeassistant."):
            raise ImportError("HA imports are forbidden in the offline quality profiler")
        return None


def load_sources(source_root):
    sys.dont_write_bytecode = True
    sys.meta_path.insert(0, BlockHA())
    sys.path.insert(0, str(source_root.resolve()))
    modules = {name: importlib.import_module(name) for name in (
        "custom_components.adaptive_solar.core.archive", "custom_components.adaptive_solar.core.actual_quality",
        "scripts.continuous_quality", "scripts.capture_actuals", "scripts.actual_quality_io")}
    origins = {}
    for name, module in list(sys.modules.items()):
        if (name == "homeassistant" or name.startswith("homeassistant.")):
            raise ImportError("HA unexpectedly loaded")
        if name.startswith(("custom_components", "scripts")) and getattr(module, "__file__", None):
            path = Path(module.__file__).resolve()
            if not path.is_relative_to(source_root.resolve()):
                raise ImportError("Mixed source roots in quality profiler")
            origins[name] = str(path.relative_to(source_root.resolve()))
    return modules, origins


def decisions(result):
    """Remove new availability/provenance times, retain actual values and gates."""
    report = result["quality_derivation"]
    normalization = result["normalization"]
    return {"capture_metadata": {key: value for key, value in result.items()
                                 if key not in {"quality_derivation", "normalization", "quality", "normalized_at"}},
            "quality_derivation": {key: value for key, value in report.items()
                                   if key not in {"as_of", "generated_at", "quality"}},
            "masks": report["quality"]["intervals"],
            "records": [{k: v for k, v in row.items() if k != "observed_at"}
                        for row in normalization["records"]], "excluded": normalization["excluded"]}


class Phases:
    def __init__(self):
        self.values = {}
        self.markers = {}
        self.started = None
        self.build_ended = None

    def add(self, label, wall, cpu, **counts):
        row = self.values.setdefault(label, {"calls": 0, "wall_seconds_inclusive": 0.0,
                                             "cpu_seconds_inclusive": 0.0})
        row["calls"] += 1
        row["wall_seconds_inclusive"] += wall
        row["cpu_seconds_inclusive"] += cpu
        for key, value in counts.items():
            row[key] = row.get(key, 0) + value

    def wrap(self, original, label):
        @functools.wraps(original)
        def measured(*args, **kwargs):
            begin, cpu = time.perf_counter(), time.process_time()
            if label == "quality.build_quality":
                self.markers["derive_to_build_wall_seconds"] = begin - self.started
                self.markers["selected_interval_events"] = len(args[0])
                self.markers["configuration_proofs"] = len(kwargs.get("configurations", []))
            result = original(*args, **kwargs)
            end = time.perf_counter()
            counts = {}
            if label == "quality._hour":
                counts["interval_candidates"] = len(args[0])
            if label == "quality._intervals":
                counts["prepared_intervals"] = len(result)
            if label == "gzip.read":
                counts["decompressed_bytes"] = len(result)
            if label == "archive._read_original":
                counts["compressed_bytes"] = args[1].stat().st_size
                counts["events"] = len(result["page"]["events"])
            self.add(label, end - begin, time.process_time() - cpu, **counts)
            if label == "quality.build_quality":
                self.build_ended = end
            return result
        return measured

    def generator(self, original):
        @functools.wraps(original)
        def measured(*args, **kwargs):
            iterator = iter(original(*args, **kwargs))
            try:
                while True:
                    begin, cpu = time.perf_counter(), time.process_time()
                    try:
                        value = next(iterator)
                    except StopIteration:
                        self.add("archive.iter_events_next", time.perf_counter() - begin, time.process_time() - cpu)
                        return
                    self.add("archive.iter_events_next", time.perf_counter() - begin, time.process_time() - cpu,
                             events_yielded=1)
                    yield value
            finally:
                iterator.close()
        return measured


def validate_worker_output(args):
    outputs = [args.output]
    if args.worker_mode == "cprofile":
        outputs.extend([args.output.with_suffix(".prof"), args.output.with_suffix(".txt")])
    protected_files = {p.resolve() for p in (args.raw, args.bindings, args.expected_manifest)}
    protected_roots = [p.resolve() for p in (args.archive, args.source_root)]
    for path in outputs:
        if (path.exists() or path.is_symlink() or path.resolve() in protected_files
                or any(path.resolve().is_relative_to(root) for root in protected_roots)):
            raise ValueError("Worker outputs must be new files outside frozen inputs and source tree")


def measured_worker(args):
    validate_worker_output(args)
    output = args.output.resolve()
    before = inventories(args)
    expected = json.loads(args.expected_manifest.read_text())
    if before != expected:
        raise ValueError("Frozen inputs or pinned sources changed before worker")
    raw = json.loads(args.raw.read_text())
    bindings = json.loads(args.bindings.read_text())
    # Python 3.14 resolves this lazily through trusted stdlib before pinned
    # scientific imports (e.g. h5py) query it. Child execution stays blocked
    # throughout all subsequent pinned-source imports and derivation.
    platform.processor()

    def no_network(event, values):
        if event in {"socket.connect", "socket.bind", "socket.getaddrinfo", "subprocess.Popen", "os.system"}:
            raise RuntimeError("Network and child execution forbidden inside measured worker")
    sys.addaudithook(no_network)
    modules, origins = load_sources(args.source_root)
    archive = modules["custom_components.adaptive_solar.core.archive"]
    quality = modules["custom_components.adaptive_solar.core.actual_quality"]
    continuous = modules["scripts.continuous_quality"]
    phases = Phases() if args.worker_mode == "phases" else None

    class FrozenReader(archive.ArchiveStore):
        def __init__(self):
            self.root = args.archive.resolve()
            self.originals = self.root / "originals"

        def _db(self, path=None, **kwargs):
            if path is not None and Path(path).resolve() != self.root / "index.sqlite3":
                raise ValueError("Alternate database forbidden")
            return readonly_db(self.root)

    @contextmanager
    def frozen_lock(root):
        if Path(root).resolve() != args.archive.resolve():
            raise ValueError("Unexpected archive lock root")
        yield

    profiler = cProfile.Profile() if args.worker_mode == "cprofile" else None
    with ExitStack() as stack:
        stack.enter_context(patch.object(archive, "_lock", frozen_lock))
        if phases:
            for name in ("build_quality", "_events", "_bindings", "_intervals", "_config_changes", "_hour",
                         "configuration_from_forecast", "_configuration_inputs", "_forecast"):
                if hasattr(quality, name):
                    stack.enter_context(patch.object(quality, name, phases.wrap(getattr(quality, name), "quality." + name)))
            for name in ("_read_original", "resolve_events"):
                stack.enter_context(patch.object(archive.ArchiveStore, name,
                                                 phases.wrap(getattr(archive.ArchiveStore, name), "archive." + name)))
            stack.enter_context(patch.object(archive.ArchiveStore, "iter_events",
                                             phases.generator(archive.ArchiveStore.iter_events)))
            stack.enter_context(patch.object(gzip.GzipFile, "read", phases.wrap(gzip.GzipFile.read, "gzip.read")))
            stack.enter_context(patch.object(json, "loads", phases.wrap(json.loads, "json.loads")))
            # Aliases imported into source modules must all observe the same wrapped function.
            for name in ("canonical_bytes", "validate_page", "validate_envelope"):
                original = getattr(archive, name)
                wrapped = phases.wrap(original, "archive." + name)
                for module in list(sys.modules.values()):
                    if getattr(module, "__name__", "").startswith(("scripts", "custom_components.adaptive_solar")):
                        if getattr(module, name, None) is original:
                            stack.enter_context(patch.object(module, name, wrapped))
        reader = FrozenReader()
        if profiler:
            profiler.enable()
        wall, cpu = time.perf_counter(), time.process_time()
        if phases:
            phases.started = wall
        result = continuous.derive(reader, raw, bindings)
        elapsed, cpu_elapsed = time.perf_counter() - wall, time.process_time() - cpu
        real_finished_at = datetime.now(UTC)
        if profiler:
            profiler.disable()
    if (result["raw"] != raw["raw"] or result["retrieved_at"] != raw["retrieved_at"]
            or result["capture_id"] != raw["capture_id"] or inventories(args) != before):
        raise ValueError("Frozen input bytes changed during derivation")
    report = result["quality_derivation"]
    generated = datetime.fromisoformat(report["generated_at"])
    validation = datetime.fromisoformat(report["quality"]["provenance"]["validated_at"])
    capture_validation = datetime.fromisoformat(result["quality"]["provenance"]["validated_at"])
    expected_availability = max(datetime.fromisoformat(raw["retrieved_at"]), validation)
    if (not datetime.fromisoformat(report["as_of"]) <= generated <= real_finished_at
            or validation != generated or capture_validation != generated
            or datetime.fromisoformat(result["normalized_at"]) != generated
            or any(datetime.fromisoformat(row["observed_at"]) != expected_availability
                   for row in result["normalization"]["records"])):
        raise ValueError("Real validation/availability chronology disagrees with derived records")
    metrics = {"mode": args.worker_mode, "wall_seconds": elapsed, "cpu_seconds": cpu_elapsed,
               "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
               "decision_sha256": digest(decisions(result)), "result_sha256": digest(result),
               "as_of": result["quality_derivation"]["as_of"],
               "generated_at": result["quality_derivation"]["generated_at"],
               "accepted_records": len(result["normalization"]["records"]),
               "excluded_records": len(result["normalization"]["excluded"]),
               "summary": result["quality_derivation"]["summary"], "import_origins": origins,
               "input_manifest_sha256": digest(before), "input_bytes_unchanged": True,
               "input_raw_and_receipt_preserved": True,
               "availability_chronology_verified": True, "real_finished_at": real_finished_at.isoformat()}
    if phases:
        phases.markers["build_to_derive_end_wall_seconds"] = elapsed + wall - phases.build_ended
        metrics.update(phases=phases.values, phase_markers=phases.markers,
                       phase_note="Nested inclusive wall/CPU durations overlap; never add them. Generator next excludes consumer work.")
    if profiler:
        profiler.dump_stats(str(output.with_suffix(".prof")))
        with output.with_suffix(".txt").open("x") as stream:
            pstats.Stats(profiler, stream=stream).strip_dirs().sort_stats("cumulative").print_stats(70)
    write_json(output, metrics)


def environment(args):
    packages = {}
    for name in ("pvlib", "scikit-learn", "numpy", "pandas", "aiohttp", "homeassistant"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    return {"python": sys.version, "executable": sys.executable, "platform": platform.platform(),
            "cpu": next((line.partition(":")[2].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                         if line.startswith("model name")), platform.machine()), "logical_cpus": os.cpu_count(),
            "dependencies": packages, "command": [sys.executable, *sys.argv],
            "harness_sha256": file_hash(Path(__file__)), "recorded_at": datetime.now(UTC).isoformat(),
            "source_label": args.source_label,
            "cache_state": "Original byte hashing immediately before measurement primes OS cache; no cold-cache claim",
            "reader_scope": "Pinned native original validation/selection; readonly SQLite; no initialization/reconcile/writer lock",
            "timing_scope": "derive only; imports/input hashing/result hashing/output writing excluded; no host/HA/network"}


def worker_environment():
    """Offline children receive locale/search settings, never inherited keys."""
    allowed = {name: value for name, value in os.environ.items()
               if name in {"PATH", "LANG", "TZ"} or name.startswith("LC_")}
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        allowed[name] = "1"
    return allowed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True, help="Frozen local archive snapshot; no live archive")
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--bindings", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True, help="Explicit pinned public source tree")
    parser.add_argument("--source-label", default="unlabelled-content-hashes-authoritative")
    parser.add_argument("--output", type=Path, required=True, help="New private result directory")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=900, help="Per-worker seconds, at most 1800")
    parser.add_argument("--cprofile", action="store_true", help="Additional separate cProfile run; can be much slower")
    parser.add_argument("--max-batches", type=int, default=50000)
    parser.add_argument("--max-events", type=int, default=2000000)
    parser.add_argument("--max-archive-bytes", type=int, default=4 * GIB)
    parser.add_argument("--max-decompressed-bytes", type=int, default=4 * GIB)
    parser.add_argument("--memory-bytes", type=int, default=4 * GIB)
    parser.add_argument("--worker-mode", choices=("ordinary", "phases", "cprofile"), help=argparse.SUPPRESS)
    parser.add_argument("--expected-manifest", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if (platform.system() != "Linux" or not 1 <= args.repeats <= 5 or not 1 <= args.timeout <= 1800
            or not 1 <= args.max_batches <= 50000 or not 1 <= args.max_events <= 2000000
            or not MIB <= args.max_archive_bytes <= 4 * GIB
            or not MIB <= args.max_decompressed_bytes <= 4 * GIB
            or not 512 * MIB <= args.memory_bytes <= 8 * GIB):
        parser.error("Requires Linux and bounded repeats/time/archive/events/memory")
    for name in ("archive", "raw", "bindings", "source_root", "output"):
        setattr(args, name, getattr(args, name).absolute())
    os.umask(0o077)
    if args.worker_mode:
        resource.setrlimit(resource.RLIMIT_AS, (args.memory_bytes, args.memory_bytes))
        measured_worker(args)
        return 0
    output = args.output.resolve()
    if (args.output.exists() or args.output.is_symlink()
            or any(output.is_relative_to(path.resolve()) for path in (args.archive, args.source_root))
            or output in {args.raw.resolve(), args.bindings.resolve()}):
        parser.error("Output must be a new directory outside frozen inputs and source tree")
    frozen = inventories(args)
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "input-manifest.json", frozen)
    write_json(args.output / "environment.json", environment(args))
    runs = []
    modes = ["ordinary"] * args.repeats + ["phases"] + (["cprofile"] if args.cprofile else [])
    for number, mode in enumerate(modes, start=1):
        worker_output = args.output / f"{number}-{mode}.json"
        command = [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--worker-mode", mode,
                   "--expected-manifest", str(args.output / "input-manifest.json")]
        for name in ("archive", "raw", "bindings", "source_root", "max_batches", "max_events", "max_archive_bytes",
                     "max_decompressed_bytes", "memory_bytes"):
            command.extend(["--" + name.replace("_", "-"), str(getattr(args, name))])
        command.extend(["--output", str(worker_output)])
        started = time.perf_counter()
        subprocess.run(command, check=True, timeout=args.timeout, env=worker_environment())
        run = json.loads(worker_output.read_text())
        run["subprocess_wall_seconds"] = time.perf_counter() - started
        if runs and run["decision_sha256"] != runs[0]["decision_sha256"]:
            raise ValueError("Real-clock runs changed factual quality decisions; inspect availability differences")
        runs.append(run)
        summary = {"status": "partial", "runs": runs, "repeats": args.repeats,
                   "decision_sha256": runs[0]["decision_sha256"],
                   "p95": None, "p95_note": "Few runs, no defensible tail estimate",
                   "ordinary_median_wall_seconds": statistics.median(r["wall_seconds"] for r in runs if r["mode"] == "ordinary")}
        # Progress receipts use a new name so an interrupted run retains earlier evidence.
        write_json(args.output / f"summary-{number}.json", summary)
        print(json.dumps({key: run[key] for key in ("mode", "wall_seconds", "cpu_seconds", "accepted_records",
                                                  "excluded_records", "decision_sha256")}), flush=True)
    if inventories(args) != frozen:
        raise ValueError("Frozen input manifest changed after measurements")
    write_json(args.output / "complete.json", {**summary, "status": "complete", "input_bytes_unchanged": True,
                                               "completed_at": datetime.now(UTC).isoformat(),
                                               "input_manifest_sha256": digest(frozen)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
