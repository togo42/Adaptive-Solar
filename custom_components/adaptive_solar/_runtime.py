# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Torsten Godau
"""Narrow HA-native ML bootstrap, before any coordinator or persistent writer.

HA 2026.11 no longer mounts /config/deps. Most platforms use the upstream wheel;
the qualified musl target uses a hash-pinned source-delivery bundle. This is an
explicit exception to manifest-only dependencies, not a second package manager.
"""
from __future__ import annotations

import asyncio
from importlib import metadata
import json
from pathlib import Path
import platform
import re
import sys
import sysconfig

ML_VERSION = "1.9.1"
ML_REQUIREMENT = "scikit-learn==" + ML_VERSION
STATE_KEY = "adaptive_solar_runtime_bootstrap"


class RuntimeDependencyError(RuntimeError):
    """Required ML runtime is unavailable without changing a running library."""


def runtime_contract() -> dict:
    try:
        contract = json.loads(Path(__file__).with_name("runtime_requirements.json").read_bytes())
    except (OSError, ValueError) as exc:
        raise RuntimeDependencyError("Cannot read the Adaptive Solar runtime dependency contract") from exc
    if (not isinstance(contract, dict) or type(contract.get("schema")) is not int
            or contract.get("schema") != 1 or contract.get("requirements") != [ML_REQUIREMENT]):
        raise RuntimeDependencyError("Invalid Adaptive Solar runtime dependency contract")
    if not isinstance(contract.get("musl_requirement"), str) or not re.fullmatch(
        r"scikit-learn@https://github\.com/togo42/Adaptive-Solar/releases/download/"
        r"v[0-9A-Za-z.+-]+/scikit_learn-1\.9\.1\.tar\.gz#sha256=[0-9a-f]{64}",
        contract.get("musl_requirement", ""),
    ):
        raise RuntimeDependencyError("ML delivery URL must be an explicit SHA256-pinned project release")
    return contract


def probe_runtime() -> bool:
    """Run in HA's executor; metadata alone never certifies native imports."""
    try:
        installed = metadata.version("scikit-learn")
    except metadata.PackageNotFoundError:
        if any(name == "sklearn" or name.startswith("sklearn.") for name in tuple(sys.modules)):
            raise RuntimeDependencyError("scikit-learn modules are loaded without matching package metadata; restart required")
        return False
    if installed != ML_VERSION:
        raise RuntimeDependencyError(
            f"Adaptive Solar requires scikit-learn exactly {ML_VERSION}, found {installed}; "
            "refusing to replace a shared installed library"
        )
    try:
        import sklearn
        from sklearn.ensemble import GradientBoostingRegressor

        if sklearn.__version__ != ML_VERSION or not callable(GradientBoostingRegressor):
            raise RuntimeDependencyError("Loaded scikit-learn does not match the exact dependency contract")
    except Exception as exc:
        raise RuntimeDependencyError(
            "Installed scikit-learn cannot import the required native learner; "
            "refusing in-process repair or module reload"
        ) from exc
    return True


def installation_requirement() -> str:
    """Select delivery only for the actual qualified interpreter, never a host guess."""
    contract = runtime_contract()
    soabi = sysconfig.get_config_var("SOABI")
    if (sys.implementation.name != "cpython" or sys.version_info[:2] != (3, 14)
            or sys.platform != "linux" or platform.machine().lower() not in {"x86_64", "amd64"}
            or sysconfig.get_config_var("Py_GIL_DISABLED")):
        raise RuntimeDependencyError("Automatic ML delivery is qualified only for normal CPython 3.14, Linux x86_64")
    if soabi == "cpython-314-x86_64-linux-musl":
        return contract["musl_requirement"]
    if soabi == "cpython-314-x86_64-linux-gnu":
        return ML_REQUIREMENT
    raise RuntimeDependencyError("Unsupported ML delivery ABI; no compiler fallback or legacy import-path patch is attempted")


async def async_ensure_runtime(hass) -> None:
    """Serialize entries, respect installation opt-outs, and fail before store setup."""
    # These imports stay inside the HA-only function: offline core imports never
    # import Home Assistant and the archive host still has no HA dependency.
    from homeassistant.requirements import async_process_requirements

    state = hass.data.setdefault(STATE_KEY, {"lock": asyncio.Lock(), "ready": False, "interrupted": False})
    async with state["lock"]:
        if state["interrupted"]:
            raise RuntimeDependencyError("An ML installation was interrupted; wait for Core's installer and restart before retrying")
        if await hass.async_add_executor_job(probe_runtime):
            state["ready"] = True
            return
        if state["ready"]:
            raise RuntimeDependencyError("ML runtime disappeared after successful setup; refusing a package change during entry reload")
        skipped = {
            name.lower().replace("_", "-").replace(".", "-")
            for name in getattr(hass.config, "skip_pip_packages", [])
        }
        if hass.config.skip_pip or "scikit-learn" in skipped:
            raise RuntimeDependencyError("scikit-learn is missing and automatic installation is disabled by Home Assistant")
        requirement = await hass.async_add_executor_job(installation_requirement)
        try:
            # Core owns its installer, executor, shared pip lock and constraints.
            # No subprocess, pip invocation, import-path change or global cache
            # policy belongs to the integration.
            await async_process_requirements(hass, "adaptive_solar", [requirement], is_built_in=False)
            if not await hass.async_add_executor_job(probe_runtime):
                raise RuntimeDependencyError("Core's ML installation returned without the required library")
        except asyncio.CancelledError:
            # The native installer may still be finishing in an executor. Never
            # start a competing attempt or activate a coordinator after timeout.
            state["interrupted"] = True
            raise
        state["ready"] = True
