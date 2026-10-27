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


def validate_snapshot(day, snapshot, metadata, site: SiteConfig):
    """Validate original limits/timezone, never reinterpret old energy at new caps."""
    if (not isinstance(day, str) or date.fromisoformat(day).isoformat() != day
            or not isinstance(snapshot, dict) or set(snapshot) != {"issued_at", "energies"}
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
    return deepcopy(snapshot), deepcopy(metadata)
