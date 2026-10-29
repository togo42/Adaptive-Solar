"""Frozen issued forecasts have provenance independent of training eligibility."""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime, time, timedelta
import hashlib
import json
import math
from zoneinfo import ZoneInfo

from .core.models import SiteConfig, utc_time


def digest(value, length=64):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:length]


def config_fingerprints(site: SiteConfig):
    full = site.to_dict()
    if full.get("irradiance_entity_id") is None:
        full.pop("irradiance_entity_id", None)
    shade = {k: v for k, v in full.items() if k != "forecast_days"}
    history = site.to_dict()
    for key in ("weather_models", "forecast_days", "temperature_entity_id", "wind_entity_id", "irradiance_entity_id"):
        history.pop(key, None)
    for inverter in history["inverters"]:
        inverter.pop("power_entity_id", None)
    return digest(full, 16), digest(history), digest(shade)


def provenance(site: SiteConfig, *, source="forecast_archive"):
    full, history, _ = config_fingerprints(site)
    identity = {"latitude": site.latitude, "longitude": site.longitude, "timezone": site.timezone,
                "stages": sorted((inv.id, inv.output_type) for inv in site.inverters)}
    return {"schema": 1, "site_identity": digest(identity), "config_fingerprint": full,
            "history_fingerprint": history, "timezone": site.timezone,
            "output_caps_kw": {inv.id: inv.output_cap_w / 1000 for inv in site.inverters}, "source": source}


def make_snapshot(result, start, end, site: SiteConfig):
    """Freeze full-precision native energies and their complete absolute-hour curve together."""
    energies = {inv.id: result.energy_kwh(start, end, inv.id) for inv in site.inverters}
    if any(value is None for value in energies.values()):
        return None
    curves = {inv.id: [] for inv in site.inverters}
    cursor = start
    while cursor < end:
        stop = min(cursor + timedelta(hours=1), end)
        for inverter in site.inverters:
            curves[inverter.id].append({"start": cursor.isoformat(), "end": stop.isoformat(),
                                        "energy_kwh": result.energy_kwh(cursor, stop, inverter.id)})
        cursor = stop
    return {"issued_at": result.issued_at.isoformat(), "energies": energies, "forecast": curves}


def snapshot_curve(snapshot, inverter_ids):
    """Combine aligned frozen cells without reconstructing missing legacy curves."""
    curves = snapshot.get("forecast", {}) if snapshot else {}
    ids = tuple(inverter_ids)
    if not ids or any(key not in curves for key in ids):
        return []
    return [{"start": cell["start"], "end": cell["end"],
             "energy_kwh": sum(curves[key][index]["energy_kwh"] for key in ids)}
            for index, cell in enumerate(curves[ids[0]])]


def validate_snapshot(day, snapshot, metadata, site: SiteConfig, *, strict_curve=True):
    """Validate original limits/timezone, never reinterpret old energy at new caps."""
    if (not isinstance(day, str) or date.fromisoformat(day).isoformat() != day
            or not isinstance(snapshot, dict) or set(snapshot) not in (
                {"issued_at", "energies"}, {"issued_at", "energies", "forecast"})
            or not isinstance(metadata, dict) or type(metadata.get("schema")) is not int or metadata["schema"] != 1
            or set(metadata) != {"schema", "site_identity", "config_fingerprint", "history_fingerprint",
                                 "timezone", "output_caps_kw", "source"}
            or metadata.get("timezone") != site.timezone
            or metadata.get("site_identity") != provenance(site)["site_identity"]
            or metadata.get("source") not in {"forecast_archive", "operator_restore"}):
        raise ValueError("invalid snapshot provenance")
    for key, length in (("config_fingerprint", 16), ("history_fingerprint", 64)):
        value = metadata.get(key)
        if not isinstance(value, str) or len(value) != length or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("invalid snapshot fingerprint")
    caps = metadata.get("output_caps_kw")
    energies = snapshot["energies"]
    ids = {inv.id for inv in site.inverters}
    if not isinstance(caps, dict) or set(caps) != ids or not isinstance(energies, dict) or set(energies) != ids:
        raise ValueError("invalid snapshot stages")
    start = datetime.combine(date.fromisoformat(day), time.min, ZoneInfo(site.timezone)).astimezone(UTC)
    end = datetime.combine(date.fromisoformat(day) + timedelta(days=1), time.min, ZoneInfo(site.timezone)).astimezone(UTC)
    if utc_time(datetime.fromisoformat(snapshot["issued_at"])) > start:
        raise ValueError("snapshot issued after day start")
    for key, cap in caps.items():
        value = energies[key]
        if (isinstance(cap, bool) or not isinstance(cap, (int, float)) or not math.isfinite(cap) or not 0 < cap <= 1e6
                or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                or not 0 <= value <= cap * (end - start).total_seconds() / 3600 * 1.1):
            raise ValueError("invalid day-start energy")
    clean = deepcopy(snapshot)
    if "forecast" in clean:
        try:
            _validate_curve(clean["forecast"], ids, start, end, caps, energies)
        except (TypeError, ValueError, OverflowError):
            if strict_curve:
                raise ValueError("invalid day-start curve") from None
            # A damaged optional display curve must not reset valid daily
            # totals or unrelated meter/learning history on legacy-store load.
            clean.pop("forecast")
    return clean, deepcopy(metadata)


def _validate_curve(curves, ids, start, end, caps, energies):
    if not isinstance(curves, dict) or set(curves) != ids:
        raise ValueError("invalid day-start curve stages")
    for key, cells in curves.items():
        if not isinstance(cells, list) or not 1 <= len(cells) <= 26:
            raise ValueError("invalid day-start curve size")
        cursor, total = start, 0.0
        for cell in cells:
            if not isinstance(cell, dict) or set(cell) != {"start", "end", "energy_kwh"}:
                raise ValueError("invalid day-start curve cell")
            begin = utc_time(datetime.fromisoformat(cell["start"]))
            stop = utc_time(datetime.fromisoformat(cell["end"]))
            value = cell["energy_kwh"]
            expected_end = min(cursor + timedelta(hours=1), end)
            if (begin != cursor or stop != expected_end or stop <= begin
                    or isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or not 0 <= value <= caps[key] * (stop - begin).total_seconds() / 3600 * 1.1):
                raise ValueError("invalid day-start curve coverage or energy")
            cursor, total = stop, total + value
        if cursor != end or not math.isclose(total, energies[key], rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError("day-start curve does not match daily energy")
