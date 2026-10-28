"""Frozen Open-Meteo member trajectories for host-side research, never HA selection.

The raw response remains authoritative. A member is one complete meteorological
trajectory, and unavailable cells remain gaps. API receipt is not model run time.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re

from .models import SiteConfig, WeatherForecast, utc_time

VARIABLES = ("shortwave_radiation", "direct_normal_irradiance", "diffuse_radiation",
             "temperature_2m", "wind_speed_10m", "cloud_cover")
UNITS = dict(zip(VARIABLES, ("W/m²", "W/m²", "W/m²", "°C", "m/s", "%"), strict=True))
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
DEFAULT_DETERMINISTIC = ("best_match", "icon_d2", "icon_eu", "ecmwf_ifs", "gfs_global")
DEFAULT_ENSEMBLES = ("dwd_icon_d2_eps", "ecmwf_ifs_europe_ensemble", "ecmwf_ifs025_ensemble")
ENSEMBLE_COUNTS = {"dwd_icon_d2_eps": 20, "ecmwf_ifs_europe_ensemble": 51, "ecmwf_ifs025_ensemble": 51}
FAMILIES = {"dwd_icon_d2_eps": "icon", "ecmwf_ifs_europe_ensemble": "ifs", "ecmwf_ifs025_ensemble": "ifs"}


@dataclass(frozen=True)
class MemberArchive:
    product: str
    family: str
    received_at: datetime
    expected_members: int
    members: tuple[WeatherForecast, ...]
    missing_members: tuple[int, ...]
    rejected_members: dict[int, str]

    @property
    def parsed_member_count(self):
        """Parsed members; per-window completeness must still be checked."""
        return len(self.members)


def request_params(latitude: float, longitude: float, model: str, hours: int = 193) -> dict:
    """One prior endpoint plus requested forward cells; no calendar-day truncation."""
    from .models import finite_number

    latitude = finite_number(latitude, "latitude", -90, 90)
    longitude = finite_number(longitude, "longitude", -180, 180)
    if isinstance(hours, bool) or not isinstance(hours, int) or not 1 <= hours <= 385:
        raise ValueError("hours must be an integer from 1 to 385")
    if not isinstance(model, str) or re.fullmatch(r"[a-z0-9_]+", model) is None:
        raise ValueError("invalid model")
    return {"latitude": latitude, "longitude": longitude, "models": model, "hourly": ",".join(VARIABLES),
            "forecast_hours": hours, "past_hours": 1, "timezone": "UTC", "timeformat": "unixtime",
            "temperature_unit": "celsius", "wind_speed_unit": "ms"}


def field_provenance(product: str) -> dict:
    """Provider output is preserved without guessing native model semantics.

    DNI/DHI can be provider-derived. The API does not encode a per-cell derivation
    flag; lack of that flag must not be turned into a claim of native radiation.
    """
    result = {field: {"provider": "open-meteo", "api_field": field,
                      "origin": "provider_output_native_or_derived_unresolved",
                      "local_derivation": None, "product": product} for field in VARIABLES}
    # Product-specific documentary evidence, checked 2026-10-28. Never transfer
    # the deterministic 9-km HRES contract to the 9-km ensemble by name alone.
    documentation = None
    methods = {}
    if product in ("icon_d2", "icon_eu"):
        documentation = "https://open-meteo.com/en/docs/dwd-api"
        methods = {"shortwave_radiation": "sum_native_direct_and_diffuse",
                   "direct_normal_irradiance": "solar_geometry_from_direct_horizontal",
                   "wind_speed_10m": "magnitude_of_native_u_v"}
        native = ("diffuse_radiation", "temperature_2m", "cloud_cover")
    elif product in ("ecmwf_ifs", "ecmwf_ifs025"):
        documentation = "https://open-meteo.com/en/docs/ecmwf-api"
        methods = {"direct_normal_irradiance": "solar_geometry_from_direct_horizontal",
                   "wind_speed_10m": "magnitude_of_native_u_v",
                   "diffuse_radiation": ("global_minus_native_direct" if product == "ecmwf_ifs"
                                         else "razo_mueller_witwer_global_decomposition")}
        native = ("shortwave_radiation", "temperature_2m", "cloud_cover")
    if documentation is not None:
        for field in native:
            result[field].update(origin="provider_native_field_with_api_processing", documentation=documentation,
                                 checked_on="2026-10-28")
        for field, method in methods.items():
            result[field].update(origin="provider_derived", provider_derivation=method,
                                 documentation=documentation, checked_on="2026-10-28")
    return result


def parse_members(payload: dict, product: str, received_at: datetime,
                  site: SiteConfig | None = None) -> MemberArchive:
    """Strict shared endpoint parser, independently applied to every EPS member.

    Open-Meteo uses unsuffixed fields for member zero and _member01, etc.
    All six fields and units must agree on the same member and timestamps.
    """
    from ..weather import WeatherError, parse_forecast

    if product not in ENSEMBLE_COUNTS:
        raise ValueError("unsupported ensemble product")
    received_at = utc_time(received_at, "received_at")
    if not isinstance(payload, dict) or not isinstance(payload.get("hourly"), dict):
        raise ValueError("malformed ensemble response")
    hourly, units = payload["hourly"], payload.get("hourly_units", {})
    if not isinstance(units, dict) or not isinstance(hourly.get("time"), list):
        raise ValueError("malformed ensemble arrays/units")
    if units.get("time") != "unixtime":
        raise ValueError("unexpected time units")
    expected = ENSEMBLE_COUNTS[product]
    # Reject unexpected member identities instead of silently changing the cohort.
    for key in hourly:
        if not isinstance(key, str):
            raise ValueError("invalid ensemble field")
        match = re.fullmatch(r"(.+)_member(\d+)", key)
        if match and match[1] in VARIABLES:
            member_index = int(match[2])
            if not 1 <= member_index < expected or key != f"{match[1]}_member{member_index:02d}":
                raise ValueError("unexpected member identity")
    members, missing, rejected = [], [], {}
    for index in range(expected):
        suffix = "" if index == 0 else f"_member{index:02d}"
        keys = {field: field + suffix for field in VARIABLES}
        if not any(key in hourly for key in keys.values()):
            missing.append(index)
            continue
        member = {"hourly": {"time": hourly["time"]}, "hourly_units": {"time": units["time"]}}
        for field, key in keys.items():
            member["hourly"][field] = hourly.get(key)
            member["hourly_units"][field] = units.get(key)
        try:
            members.append(parse_forecast(member, f"{product}:member{index:02d}", received_at, site))
        except (WeatherError, ValueError, TypeError) as err:
            rejected[index] = str(err)
    return MemberArchive(product, FAMILIES[product], received_at, expected, tuple(members), tuple(missing), rejected)
