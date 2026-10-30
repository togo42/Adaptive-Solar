#!/usr/bin/env python3
"""Run isolated archive timer jobs with capacity checks and private status receipts."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.archive import collection_summary  # noqa: E402
from scripts.replay_paths import validate_output  # noqa: E402

GIB = 1024 ** 3
JOBS = ("ha", "weather", "observations", "retention", "status")
INPUT_PATHS = ("site_json", "actual_config", "reference_config", "quality", "quality_bindings")


def private_path(value):
    path = Path(value)
    path = (ROOT / path).resolve() if not path.is_absolute() else path.resolve()
    if not path.is_relative_to((ROOT / "data").resolve()):
        raise ValueError("Host paths must stay below private data/")
    return path


def archive_size(root):
    """Allocated bytes, including index, staging and pins; never traverse links."""
    total = 0
    if root.exists():
        for directory, children, files in os.walk(root, followlinks=False):
            children[:] = [name for name in children if not (Path(directory) / name).is_symlink()]
            for name in files:
                path = Path(directory) / name
                if not path.is_symlink():
                    total += path.stat().st_blocks * 512
    return total


def capacity(root, config):
    usage = shutil.disk_usage(root)
    allocated = archive_size(root)
    floor = config.get("min_free_bytes", 2 * GIB)
    reserve = config.get("operation_reserve_bytes", GIB)
    percent = config.get("min_free_percent", 15)
    ceiling = config.get("max_archive_bytes", 4 * GIB)
    if (any(type(value) is not int or value <= 0 for value in (floor, reserve, ceiling))
            or type(percent) not in (int, float) or not 0 < percent < 100):
        raise ValueError("Invalid capacity limits")
    return {"free_bytes": usage.free, "total_bytes": usage.total, "archive_allocated_bytes": allocated,
            "min_free_bytes": floor, "operation_reserve_bytes": reserve, "max_archive_bytes": ceiling,
            "allowed": usage.free - reserve >= floor and usage.free / usage.total * 100 >= percent
            and allocated + reserve <= ceiling}


def child_env():
    env = os.environ.copy()
    directory = env.get("CREDENTIALS_DIRECTORY")
    if directory:
        auth = json.loads((Path(directory) / "ha-auth").read_text())
        if set(auth) != {"HA_URL", "HA_TOKEN"} or any(not isinstance(v, str) or not v for v in auth.values()):
            raise ValueError("Invalid runtime HA credential")
        env.update(auth)
    return env


def commands(job, config, archive):
    sources = [row["source"] for row in config["entries"]]
    sources += [config["weather_source"], config["observations_source"], config["observations_source"] + ":actuals",
                config["observations_source"] + ":references"]
    if any(not isinstance(source, str) or not source.strip() for source in sources) or len(sources) != len(set(sources)):
        raise ValueError("Archive source identities must remain separate")
    python = sys.executable
    base = [python, str(ROOT / "scripts/archive.py"), "--root", str(archive)]
    if job == "ha":
        entries = config["entries"]
        if not entries:
            raise ValueError("HA sources must be unique and nonempty")
        return [base + ["collect", "--source", row["source"], "--entry-id", row["entry_id"]] for row in entries]
    if job == "weather":
        return [[python, str(ROOT / "scripts/capture_weather.py"), "--archive", str(archive),
                 "--source", config["weather_source"], "--site-json", str(private_path(config["site_json"])),
                 "--hours", "193"]]
    if job == "observations":
        if config.get("quality") and config.get("quality_bindings"):
            raise ValueError("Choose static quality or continuous bindings")
        if config.get("quality_bindings") and not config.get("actual_config"):
            raise ValueError("Continuous quality requires actual mapping")
        command = [python, str(ROOT / "scripts/archive_observations.py"), "--archive", str(archive),
                   "--source", config["observations_source"], "--lookback-hours", "72", "--lag-minutes", "10"]
        for key, option in (("actual_config", "--actual-config"), ("reference_config", "--reference-config"),
                            ("quality", "--quality"), ("quality_bindings", "--quality-bindings")):
            if config.get(key):
                command.extend([option, str(private_path(config[key]))])
        if not config.get("actual_config") and not config.get("reference_config"):
            raise ValueError("Observation mapping required")
        return [command]
    if job == "retention":
        return [base + ["maintain"]]
    return []


def write_status(path, value):
    fd, name = tempfile.mkstemp(prefix=".host-status-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(name).unlink(missing_ok=True)


def run(job, config, *, config_path=None):
    archive_path = Path(config["archive"])
    if not archive_path.is_absolute():
        archive_path = ROOT / archive_path
    archive = private_path(archive_path)
    state = Path(config.get("status_dir", "data/host-status"))
    if not state.is_absolute():
        state = ROOT / state
    private_path(state)
    inputs = [private_path(config[key]) for key in INPUT_PATHS if config.get(key)]
    if config_path is not None:
        inputs.append(private_path(config_path))
    # Validate the entire configured output set before creating either directory.
    # Keep lexical paths here so output symlinks cannot hide behind resolve().
    for output in (state, state / "writer.lock", *(state / f"{name}.json" for name in JOBS)):
        validate_output(output, archive_path, inputs)
    archive.mkdir(parents=True, exist_ok=True, mode=0o700)
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    report = {"schema": 1, "job": job, "started_at": datetime.now(UTC).isoformat(), "commands": [], "complete": True}
    # All timer jobs share this lock, including retention and stats/index reconciliation.
    with (state / "writer.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            env = child_env() if job in {"ha", "observations"} else os.environ.copy()
            planned = commands(job, config, archive)
            for command in planned:
                report["capacity"] = capacity(archive, config)
                if job != "retention" and not report["capacity"]["allowed"]:
                    report.update(complete=False, reason="capacity_guard")
                    break
                try:
                    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=1200)
                except (OSError, subprocess.TimeoutExpired):
                    report["commands"].append({"returncode": None, "status": "failed_or_timed_out"})
                    report["complete"] = False
                    continue
                # Capture tools already sanitize errors, but their full output remains private.
                # Do not copy source IDs, credentials, endpoints or raw provider messages into journal.
                status = {"returncode": result.returncode}
                if job == "ha":
                    try:
                        status["collector"] = collection_summary(json.loads(result.stdout))
                        if not status["collector"]["complete"]:
                            status["status"] = "incomplete_collection"
                            report["complete"] = False
                    except (ValueError, TypeError, KeyError):
                        status["status"] = "invalid_collector_status"
                        report["complete"] = False
                report["commands"].append(status)
                if result.returncode:
                    report["complete"] = False
            stats = subprocess.run([sys.executable, str(ROOT / "scripts/archive.py"), "--root", str(archive), "stats"],
                                   capture_output=True, text=True, timeout=300)
            if stats.returncode == 0:
                values = json.loads(stats.stdout)
                report["archive"] = {key: values[key] for key in (
                    "batches", "events", "compressed_bytes", "index_bytes", "observation_days",
                    "compressed_bytes_per_day", "projected_24_month_compressed_bytes")}
            else:
                report.update(complete=False, stats_failed=True)
            report["capacity"] = capacity(archive, config)
        except (ValueError, TypeError, KeyError, OSError, subprocess.TimeoutExpired):
            report.update(complete=False, reason="job_failed")
        report["finished_at"] = datetime.now(UTC).isoformat()
        write_status(state / f"{job}.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", choices=JOBS)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        config_path = private_path(args.config)
        config = json.loads(config_path.read_text())
        report = run(args.job, config, config_path=config_path)
    except (OSError, ValueError, TypeError, KeyError):
        print("Archive host configuration failed.", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0 if report["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
