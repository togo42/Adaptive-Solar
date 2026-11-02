"""Local synthetic quality baseline; never opens an operator archive or HA.

Creates a new output directory, freezes its own generated inputs and measures
ArchiveStore opening plus continuous_quality.derive in fresh child processes.
The simulated clock applies only to synthetic decisions, not elapsed timers.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import cProfile
from datetime import UTC, datetime, timedelta
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import platform
import pstats
import re
import resource
import statistics
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from custom_components.adaptive_solar.const import MEASUREMENT_CONTRACT  # noqa: E402
from custom_components.adaptive_solar.core import actual_quality  # noqa: E402
from custom_components.adaptive_solar.core.archive import ArchiveStore, canonical_bytes  # noqa: E402
from custom_components.adaptive_solar.core.models import InverterConfig, SiteConfig, StringConfig  # noqa: E402
from scripts import capture_actuals, continuous_quality  # noqa: E402

START = datetime(2026, 6, 1, tzinfo=UTC)
END = START + timedelta(days=1)
AS_OF = END + timedelta(hours=2)
GENERATION = "00000000-0000-0000-0000-000000000001"
SOURCE = "synthetic-performance-source"
MAX_TOTAL_EVENTS = 100_000
MAX_TOTAL_BATCHES = 1_000


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def original_manifest(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((root / "originals").rglob("*.json.gz"))}


def envelope(sequence, kind, payload, received):
    event = {"schema": 1, "generation": GENERATION, "sequence": sequence,
             "event_id": f"synthetic-event-{sequence}", "kind": kind,
             "received_at": received.isoformat(), "payload": payload}
    return {**event, "sha256": digest(event)}


def prepare_fixture(directory, days, page_events):
    """A fixed 24h target with older irrelevant native-counter minute deltas."""
    directory.mkdir()
    inverter = InverterConfig("roof", max_ac_kw=3, energy_entity_id="sensor.synthetic_energy")
    site = SiteConfig(50, 7, "Europe/Berlin", (StringConfig("string", "roof", 3, 30, 180),),
                      (inverter,)).to_dict()
    source_binding = {"schema": 1, "energy_entity_id": "sensor.synthetic_energy",
                      "config_sha256": digest(site), "producer_sha256": "a" * 64}
    binding = {"id": "synthetic-binding", "inverter_id": "roof", "statistic_id": "sensor.synthetic_energy",
               "source": SOURCE, "generation": GENERATION, "source_inverter_id": "roof",
               "config_event_id": "synthetic-event-1", "config_sha256": digest(site),
               "producer_sha256": "a" * 64, "valid_from": (START - timedelta(hours=1)).isoformat(),
               "valid_to": (END + timedelta(days=7)).isoformat(), "measurement_kind": "native_counter",
               "curtailment_mode": "unconstrained",
               "qualification": {name: {"verified": True, "evidence": f"synthetic-only {name}",
                                          "validated_at": (START - timedelta(hours=1)).isoformat()}
                                 for name in ("configuration", "meter", "curtailment")}}
    policy = {"schema": actual_quality.CONTINUOUS_BINDINGS_SCHEMA, "bindings": [binding]}
    store = ArchiveStore(directory / "archive")
    pending, cursor, sequence, batches = [], None, 0, 0

    def add(kind, payload, received):
        nonlocal sequence, pending, cursor, batches
        sequence += 1
        pending.append(envelope(sequence, kind, payload, received))
        if len(pending) >= page_events:
            flush()

    def flush():
        nonlocal pending, cursor, batches
        if not pending:
            return
        nxt = f"{GENERATION}:{pending[-1]['sequence']}"
        page = {"schema": 1, "generation": GENERATION, "oldest_sequence": 1,
                "requested_cursor": cursor, "next_cursor": nxt, "events": pending, "gap": None}
        cursor = store.ingest_page(SOURCE, page, stored_at=AS_OF)
        pending = []
        batches += 1

    add("forecast_issued", {"issued_at": (START - timedelta(hours=1)).isoformat(), "site": site,
                            "software": {"source_sha256": "a" * 64}}, START - timedelta(hours=1))
    current = END - timedelta(days=days)
    while current < END:
        stop = current + timedelta(minutes=1)
        add("qualified_interval", {"inverter_id": "roof", "start": current.isoformat(), "end": stop.isoformat(),
                                   "observed_at": stop.isoformat(), "energy_kwh": 0.01,
                                   "measurement_contract": MEASUREMENT_CONTRACT,
                                   "continuity_id": "synthetic-lineage", "boundary_reason": None,
                                   "source_binding": source_binding}, stop)
        current = stop
    flush()
    mappings = [{"inverter_id": "roof", "statistic_ids": ["sensor.synthetic_energy"]}]
    rows, current = [], START - timedelta(hours=1)
    while current < END:
        stop = current + timedelta(hours=1)
        rows.append({"start": current.timestamp() * 1000, "end": stop.timestamp() * 1000, "change": 0.6})
        current = stop
    raw = capture_actuals.build_raw_capture(
        [{"statistic_id": "sensor.synthetic_energy", "has_sum": True, "unit_class": "energy",
          "statistics_unit_of_measurement": "kWh", "display_unit_of_measurement": "kWh"}],
        {"sensor.synthetic_energy": rows}, mappings, START, END, END + timedelta(hours=1))
    raw["capture_id"] = "synthetic-performance-capture"
    write_json(directory / "raw.json", raw)
    write_json(directory / "bindings.json", policy)
    originals = original_manifest(store.root)
    manifest = {"synthetic_only": True, "days": days, "events": sequence, "batches": batches,
                "page_events": page_events, "bindings": 1, "target_start": START.isoformat(),
                "target_end": END.isoformat(), "as_of": AS_OF.isoformat(), "active_learner": False,
                "originals_sha256": originals, "raw_sha256": digest(raw), "bindings_sha256": digest(policy),
                "input_file_sha256": {name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
                                      for name in ("raw.json", "bindings.json")},
                "compressed_original_bytes": sum(p.stat().st_size for p in store.originals.rglob("*.json.gz")),
                "archive_bytes": sum(p.stat().st_size for p in store.root.rglob("*") if p.is_file())}
    write_json(directory / "fixture.json", manifest)
    return manifest


class SyntheticClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return AS_OF.astimezone(tz) if tz else AS_OF.replace(tzinfo=None)


class CountedStore(ArchiveStore):
    """Instrumentation used exclusively by the separate profiled run."""
    def __init__(self, root):
        self.reads = {"calls": 0, "compressed_bytes": 0, "events": 0, "wall_seconds": 0.0}
        super().__init__(root)

    def _read_original(self, path):
        begin = time.perf_counter()
        result = super()._read_original(path)
        self.reads["wall_seconds"] += time.perf_counter() - begin
        self.reads["calls"] += 1
        self.reads["compressed_bytes"] += path.stat().st_size
        self.reads["events"] += len(result["page"]["events"])
        return result


def measure_worker(directory, output, profile=False):
    pattern = r"profile\.json" if profile else r"run-[1-9][0-9]*\.json"
    targets = [output, output.with_suffix(".prof"), output.with_suffix(".txt")] if profile else [output]
    if (not re.fullmatch(pattern, output.name) or output.parent.resolve() != directory.resolve()
            or directory.is_symlink() or any(p.exists() or p.is_symlink() for p in targets)):
        raise ValueError("Worker output must be new run-N.json/profile.json inside the synthetic fixture")
    raw = json.loads((directory / "raw.json").read_text())
    policy = json.loads((directory / "bindings.json").read_text())
    manifest = json.loads((directory / "fixture.json").read_text())
    if (manifest.get("synthetic_only") is not True
            or digest(raw) != manifest["raw_sha256"] or digest(policy) != manifest["bindings_sha256"]
            or any(hashlib.sha256((directory / name).read_bytes()).hexdigest() != expected
                   for name, expected in manifest["input_file_sha256"].items())
            or original_manifest(directory / "archive") != manifest["originals_sha256"]):
        raise ValueError("Frozen synthetic input changed")
    profiler = cProfile.Profile() if profile else None
    with ExitStack() as stack:
        # Deliberately no freezegun: elapsed wall/CPU timers keep their real clock.
        stack.enter_context(patch.object(continuous_quality, "datetime", SyntheticClock))
        stack.enter_context(patch.object(actual_quality, "datetime", SyntheticClock))
        if profiler:
            profiler.enable()
        wall, cpu = time.perf_counter(), time.process_time()
        store = (CountedStore if profile else ArchiveStore)(directory / "archive")
        opened_wall, opened_cpu = time.perf_counter(), time.process_time()
        result = continuous_quality.derive(store, raw, policy)
        end_wall, end_cpu = time.perf_counter(), time.process_time()
        if profiler:
            profiler.disable()
    if result["raw"] != raw["raw"] or len(result["normalization"]["records"]) != 24:
        raise ValueError("Synthetic quality behavior differs from the 24 accepted hours")
    report = result["quality_derivation"]
    decisions = {"summary": report["summary"], "masks": report["quality"]["intervals"],
                 "hours": [{key: value for key, value in row.items() if key != "evidence_event_ids"}
                           for row in report["hours"]], "normalization": result["normalization"]}
    # Provenance identifies different input event sets; it is checked by the
    # exact result digest within a fixture, separately from semantic equality.
    decisions["normalization"] = {key: value for key, value in decisions["normalization"].items()
                                  if key != "quality_provenance"}
    metrics = {"profiled": profile, "open_wall_seconds": opened_wall - wall,
               "open_cpu_seconds": opened_cpu - cpu, "derive_wall_seconds": end_wall - opened_wall,
               "derive_cpu_seconds": end_cpu - opened_cpu, "total_wall_seconds": end_wall - wall,
               "total_cpu_seconds": end_cpu - cpu,
               "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
               "result_sha256": digest(result), "accepted_records": len(result["normalization"]["records"]),
               "decision_sha256": digest(decisions),
               "evidence_events": len(result["quality_derivation"]["evidence_events"])}
    if profiler:
        metrics["original_reads"] = store.reads
        profiler.dump_stats(str(output.with_suffix(".prof")))
        with output.with_suffix(".txt").open("w") as stream:
            pstats.Stats(profiler, stream=stream).strip_dirs().sort_stats("cumulative").print_stats(45)
    write_json(output, metrics)


def environment():
    dependencies = {}
    for package in ("pvlib", "scikit-learn", "numpy", "pandas", "aiohttp"):
        try:
            dependencies[package] = version(package)
        except PackageNotFoundError:
            dependencies[package] = None
    cpu = next((line.partition(":")[2].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                if line.startswith("model name")), platform.machine())
    files = sorted([*list((ROOT / "custom_components/adaptive_solar").rglob("*.py")),
                    *list((ROOT / "scripts").glob("*.py"))])
    return {"source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "working_tree_status": subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True),
            "source_file_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
            "python": sys.version, "executable": sys.executable, "dependencies": dependencies,
            "platform": platform.platform(), "cpu": cpu, "logical_cpus": os.cpu_count(),
            "command": [sys.executable, *sys.argv], "measured_at": datetime.now(UTC).isoformat()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New directory; existing directories are rejected")
    parser.add_argument("--days", type=int, nargs="+", default=[1, 7], help="Synthetic history days, 1..30")
    parser.add_argument("--repeats", type=int, default=3, help="Fresh unprofiled workers per fixture, 1..10")
    parser.add_argument("--page-events", type=int, default=100, help="Generated events per batch, 1..1000")
    parser.add_argument("--worker-fixture", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--profile-worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker_fixture:
        measure_worker(args.worker_fixture, args.output, args.profile_worker)
        return 0
    if (not 1 <= args.repeats <= 10 or not 1 <= args.page_events <= 1000
            or not args.days or len(set(args.days)) != len(args.days) or any(not 1 <= n <= 30 for n in args.days)):
        parser.error("Bounds: distinct days 1..30, repeats 1..10, page-events 1..1000")
    events = [1 + 1440 * days for days in args.days]
    batches = sum((count + args.page_events - 1) // args.page_events for count in events)
    # Ingest reconciles existing originals per batch; bound setup work too.
    if sum(events) > MAX_TOTAL_EVENTS or batches > MAX_TOTAL_BATCHES:
        parser.error("Combined fixture budget: at most 100000 events and 1000 batches")
    if platform.system() != "Linux":
        parser.error("Peak RSS reporting currently requires Linux")
    os.umask(0o077)
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "environment.json", environment())
    summaries = []
    for days in args.days:
        directory = args.output / f"days-{days}"
        fixture = prepare_fixture(directory, days, args.page_events)
        runs = []
        for n in range(args.repeats + 1):
            profiled = n == args.repeats
            output = directory / ("profile.json" if profiled else f"run-{n + 1}.json")
            command = [sys.executable, str(Path(__file__).resolve()), "--worker-fixture", str(directory),
                       "--output", str(output)]
            if profiled:
                command.append("--profile-worker")
            begin = time.perf_counter()
            subprocess.run(command, check=True, cwd=ROOT, timeout=180)
            elapsed = time.perf_counter() - begin
            metrics = json.loads(output.read_text())
            metrics["subprocess_wall_seconds"] = elapsed
            write_json(output, metrics)
            runs.append(metrics)
        if len({row["result_sha256"] for row in runs}) != 1:
            raise ValueError("Synthetic clock-controlled output differs across repetitions")
        if summaries and runs[0]["decision_sha256"] != summaries[0]["runs"][0]["decision_sha256"]:
            raise ValueError("Synthetic quality decisions differ across history sizes")
        if original_manifest(directory / "archive") != fixture["originals_sha256"]:
            raise ValueError("Original bytes changed during measurement")
        ordinary = runs[:-1]
        summary = {"days": days, "fixture_sha256": digest(fixture), "fixture": fixture,
                   "repeats": args.repeats, "runs": runs,
                   "median": {key: statistics.median(row[key] for row in ordinary)
                              for key in ordinary[0] if key.endswith("seconds") or key == "process_peak_rss_kib"},
                   "p95": None, "p95_note": "Too few repetitions for a defensible tail estimate",
                   "cache_state": ("Fresh Python process; original bytes read before timing for integrity. "
                                   "OS cache primed by those reads; no OS cold-cache claim"),
                   "scope": "Open plus derive; no HA/network/host lock contention/capacity check/ML/export persistence"}
        summaries.append(summary)
        write_json(args.output / "summary.json", summaries)
        print(json.dumps({"days": days, "repeats": args.repeats, "median": summary["median"],
                          "batches": fixture["batches"], "events": fixture["events"]}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
