#!/usr/bin/env python3
"""Install/update the archive runtime without Home Assistant or HA test extras."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]
CONSTRAINTS = ROOT / "deploy/archive-host-constraints.txt"
CHECK = """
import importlib.metadata as md
import importlib.util
import json
import pathlib
import sys
assert sys.prefix != sys.base_prefix, 'A dedicated virtual environment is required'
assert pathlib.Path(sys.prefix).resolve() == pathlib.Path(sys.argv[1]).resolve(), 'Unexpected environment'
for name in ('homeassistant', 'pytest-homeassistant-custom-component'):
    try:
        md.version(name)
    except md.PackageNotFoundError:
        pass
    else:
        raise RuntimeError('HA package found: ' + name)
assert importlib.util.find_spec('homeassistant') is None, 'HA module still importable'
print(json.dumps({'homeassistant_installed': False, 'isolated_venv': True}))
"""


def checked(command, step, *, env):
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=1200)
    if result.returncode:
        # pip configuration or index errors can contain private endpoints.
        raise ValueError(f"Archive environment {step} failed (exit {result.returncode})")


def install(target, *, constraints=None):
    target = Path(target).absolute()
    if not CONSTRAINTS.is_file():
        raise ValueError("Mandatory archive host constraints are missing")
    if constraints is not None and not Path(constraints).is_file():
        raise ValueError("Additional runtime constraints are missing")
    if not target.exists():
        venv.EnvBuilder(with_pip=True, system_site_packages=False).create(target)
    if not (target / "pyvenv.cfg").is_file():
        raise ValueError("An archive virtual environment is required")
    config = (target / "pyvenv.cfg").read_text().lower()
    if "include-system-site-packages = false" not in config:
        raise ValueError("System site packages must be disabled")
    python = str(target / "bin/python")
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env["PYTHONNOUSERSITE"] = "1"
    checked([python, "-I", "-c", CHECK, str(target)], "preflight", env=env)
    requirements = json.loads((ROOT / "custom_components/adaptive_solar/manifest.json").read_text())["requirements"]
    command = [python, "-I", "-m", "pip", "install", "--upgrade", "--constraint", str(CONSTRAINTS)]
    if constraints is not None:
        command += ["--constraint", str(Path(constraints).resolve())]
    # Install the regular runtime only. Native HA/test extras belong in CI/dev.
    command += [str(ROOT), *requirements]
    checked(command, "installation", env=env)
    checked([python, "-I", "-m", "pip", "check"], "dependency check", env=env)
    checked([python, "-I", "-c", CHECK, str(target)], "postflight", env=env)
    return {"homeassistant_installed": False, "dependency_check": True, "runtime_requirements": requirements}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venv", required=True, type=Path)
    parser.add_argument("--constraints", type=Path, help="Optional frozen numerical/runtime dependency pins")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(install(args.venv, constraints=args.constraints), sort_keys=True))
        return 0
    except (ValueError, OSError, subprocess.TimeoutExpired):
        print("Archive runtime installation failed; require a HA-free isolated venv and compatible pins.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
