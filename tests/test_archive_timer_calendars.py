"""Exercise the shipped UTC schedules across both Berlin clock changes."""
from datetime import datetime
import os
from pathlib import Path
import re
import subprocess

import pytest


@pytest.mark.parametrize("transition", ["2026-03-29", "2026-10-25"])
@pytest.mark.parametrize("job,seconds", [("ha", 300), ("weather", 3600), ("observations", 3600),
                                        ("actuals", 21600), ("references", 3600)])
def test_archive_periodic_calendar_preserves_physical_cadence(transition, job, seconds):
    unit = Path(__file__).resolve().parents[1] / "deploy" / f"adaptive-solar-archive-{job}.timer"
    expression = next(line.split("=", 1)[1] for line in unit.read_text().splitlines()
                      if line.startswith("OnCalendar="))
    run = subprocess.run(["systemd-analyze", "calendar", f"--base-time={transition} 01:45:00",
                          "--iterations=30", expression], capture_output=True, text=True, check=True,
                         env={**os.environ, "TZ": "Europe/Berlin", "LC_ALL": "C"}, timeout=15)
    # With a non-UTC display zone systemd prints the actual UTC instants too.
    instants = [datetime.strptime(value, "%a %Y-%m-%d %H:%M:%S")
                for value in re.findall(r"\(in UTC\):\s+(.+?) UTC$", run.stdout, re.MULTILINE)]
    assert len(instants) == 30, run.stdout
    assert {(second - first).total_seconds() for first, second in zip(instants, instants[1:])} == {seconds}


@pytest.mark.parametrize("day,first_gap", [("2026-03-28", 23), ("2026-10-24", 25)])
def test_retention_remains_one_local_calendar_run_per_day(day, first_gap):
    unit = Path(__file__).resolve().parents[1] / "deploy/adaptive-solar-archive-retention.timer"
    expression = next(line.split("=", 1)[1] for line in unit.read_text().splitlines()
                      if line.startswith("OnCalendar="))
    run = subprocess.run(["systemd-analyze", "calendar", f"--base-time={day} 01:00:00", "--iterations=3",
                          expression], capture_output=True, text=True, check=True,
                         env={**os.environ, "TZ": "Europe/Berlin", "LC_ALL": "C"}, timeout=15)
    instants = [datetime.strptime(value, "%a %Y-%m-%d %H:%M:%S")
                for value in re.findall(r"\(in UTC\):\s+(.+?) UTC$", run.stdout, re.MULTILINE)]
    assert len(instants) == 3, run.stdout
    assert (instants[1] - instants[0]).total_seconds() == first_gap * 3600
