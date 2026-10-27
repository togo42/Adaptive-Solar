"""Align Open-Meteo hourly radiation and instantaneous ambient state.

Radiation at t is the source mean over [t-1h,t). Temperature, wind and cloud
at t are instantaneous: use the arithmetic mean of valid endpoints t-1h and t
as an explicit linear midpoint approximation, never a measured hourly mean.
Reference: https://open-meteo.com/en/docs#hourly-parameter-definition
(checked 2026-10-25).
No retrospective weather is requested or relabelled as an archived forecast.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import math
from typing import Any

import aiohttp

from .const import WEATHER_CACHE_SECONDS
from .core.models import SiteConfig, WeatherForecast, WeatherPoint

URL = "https://api.open-meteo.com/v1/forecast"
VARIABLES = (
    "shortwave_radiation", "direct_normal_irradiance", "diffuse_radiation",
    "temperature_2m", "wind_speed_10m", "cloud_cover",
)
UNITS = {
    "time": "unixtime", "shortwave_radiation": "W/m²",
    "direct_normal_irradiance": "W/m²", "diffuse_radiation": "W/m²",
    "temperature_2m": "°C", "wind_speed_10m": "m/s", "cloud_cover": "%",
}
# Native short-range models may end earlier; never stretch their last value.
MODEL_DAYS = {"icon_d2": 2, "icon_eu": 5, "meteofrance_arome_france": 2}
RADIATION_FIELDS = VARIABLES[:3]
AMBIENT_FIELDS = VARIABLES[3:]


class WeatherError(Exception):
    """The provider did not deliver usable weather."""


def parse_forecast(payload: dict[str, Any], model: str, issued_at: datetime,
                   site: SiteConfig | None = None, diagnostics: dict | None = None) -> WeatherForecast:
    """Align source means with linear midpoint proxies from adjacent endpoints.

    Each ambient endpoint is validated before averaging. A missing or invalid
    endpoint makes both adjoining cells unsupported; invalid radiation only
    removes its own cell. Never interpolate across a missing timestamp, mix
    forecast receipts, or extrapolate the first unsupported source interval.
    """
    if issued_at.tzinfo is None or issued_at.utcoffset() is None:
        raise ValueError("issued_at must be timezone aware")
    units = payload.get("hourly_units", {})
    if any(units.get(key) != value for key, value in UNITS.items()):
        raise WeatherError("Unexpected Open-Meteo units")
    hourly = payload.get("hourly", {})
    times = hourly.get("time", [])
    if not isinstance(times, list) or any(
        not isinstance(hourly.get(key), list) or len(hourly[key]) != len(times)
        for key in VARIABLES
    ):
        raise WeatherError("Malformed Open-Meteo hourly arrays")
    samples = {}
    normalized, rejected = [], []
    for index, stamp in enumerate(times):
        try:
            if isinstance(stamp, bool) or not isinstance(stamp, (int, float)) or not math.isfinite(stamp):
                continue
            end = datetime.fromtimestamp(stamp, UTC)
            if end in samples:
                raise WeatherError("Duplicate Open-Meteo timestamp")
            values = tuple(hourly[key][index] for key in RADIATION_FIELDS)
            radiation = _bounded_values(hourly, index, RADIATION_FIELDS, ((0, 1600),) * 3)
            if radiation is None and _small_negative_night(values, site, end):
                radiation = (0.0, 0.0, 0.0)
                normalized.append({"start": (end - timedelta(hours=1)).isoformat(), "end": end.isoformat(),
                                   "raw_w_m2": dict(zip(RADIATION_FIELDS, values, strict=True)),
                                   "normalized_w_m2": 0.0})
            elif radiation is None:
                rejected.append(end.isoformat())
            ambient = _bounded_values(hourly, index, AMBIENT_FIELDS, ((-100, 70), (0, 150), (0, 100)))
            samples[end] = radiation, ambient
        except (OverflowError, OSError, ValueError):
            continue
    points = []
    for end, (radiation, ambient) in sorted(samples.items()):
        try:
            start = end - timedelta(hours=1)
        except OverflowError:
            continue
        previous_ambient = samples.get(start, (None, None))[1]
        if radiation is None or ambient is None or previous_ambient is None:
            continue
        temp, wind, cloud = tuple((left + right) / 2 for left, right in zip(previous_ambient, ambient, strict=True))
        ghi, dni, dhi = radiation
        points.append(WeatherPoint(start=start, end=end, ghi_w_m2=ghi, dni_w_m2=dni,
                                   dhi_w_m2=dhi, temperature_c=temp, wind_m_s=wind, cloud_cover_pct=cloud))
    if not points:
        raise WeatherError("Open-Meteo returned no usable intervals")
    if diagnostics is not None:
        diagnostics.update({"policy": "small-negative-dark-hour-v1", "received_at": issued_at.isoformat(),
                            "normalized_count": len(normalized),
                            "normalized_examples": normalized[:8], "rejected_radiation_count": len(rejected),
                            "rejected_end_examples": rejected[:8]})
    return WeatherForecast(model=model, issued_at=issued_at.astimezone(UTC), points=tuple(sorted(points, key=lambda point: point.start)))


def _small_negative_night(values, site, end):
    """Normalize at most 1 W/m² numerical undershoot only in deep darkness.

    All three radiation fields must be finite numbers in [-1,0], with at least
    one negative value. A five-minute SPA grid over the entire preceding hour
    must stay below -6 degrees. Missing values, positive radiation, twilight,
    daylight, unknown location and larger negatives remain unsupported.
    """
    if (site is None or any(isinstance(v, bool) or not isinstance(v, (int, float))
                           or not math.isfinite(v) or not -1 <= v <= 0 for v in values)
            or not any(v < 0 for v in values)):
        return False
    from .core.physics import PhysicsUnavailable, solar_position

    try:
        return all(solar_position(site, end - timedelta(minutes=5 * step)).elevation_deg <= -6
                   for step in range(13))
    except PhysicsUnavailable:
        return False


def _bounded_values(hourly, index, fields, bounds):
    values = tuple(hourly[key][index] for key in fields)
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
           or not low <= value <= high for value, (low, high) in zip(values, bounds, strict=True)):
        return None
    return values


class OpenMeteoClient:
    """One cache per config entry, bounded by the selected weather models."""

    def __init__(self, session: aiohttp.ClientSession, config: SiteConfig) -> None:
        self.session = session
        self.config = config
        self._cache: dict[str, WeatherForecast] = {}
        self.errors: dict[str, str] = {}
        self.diagnostics: dict[str, dict] = {}

    async def async_forecasts(self, now: datetime) -> tuple[WeatherForecast, ...]:
        """Fetch independent model arms, retaining only a fresh successful cache."""
        results = await asyncio.gather(*(self._async_model(model, now) for model in self.config.weather_models), return_exceptions=True)
        forecasts = []
        for model, result in zip(self.config.weather_models, results, strict=True):
            if isinstance(result, BaseException):
                self.errors[model] = type(result).__name__
            else:
                self.errors.pop(model, None)
                forecasts.append(result)
        if not forecasts:
            raise WeatherError("No weather model is available")
        return tuple(forecasts)

    async def _async_model(self, model: str, now: datetime) -> WeatherForecast:
        cached = self._cache.get(model)
        if cached and 0 <= (now - cached.issued_at).total_seconds() < WEATHER_CACHE_SECONDS:
            return cached
        params = {
            "latitude": self.config.latitude, "longitude": self.config.longitude,
            "hourly": ",".join(VARIABLES), "models": model,
            "forecast_days": min(self.config.forecast_days + 1, MODEL_DAYS.get(model, 16)),
            "timezone": "UTC", "timeformat": "unixtime",
            "temperature_unit": "celsius", "wind_speed_unit": "ms",
        }
        try:
            async with asyncio.timeout(20):
                async with self.session.get(URL, params=params) as response:
                    response.raise_for_status()
                    payload = await response.json()
            # Receipt time, not request start or an invented NWP model run time.
            received = datetime.now(UTC)
            diagnostics = {}
            forecast = await asyncio.to_thread(parse_forecast, payload, model, received, self.config, diagnostics)
        except (aiohttp.ClientError, TimeoutError, ValueError, TypeError) as err:
            raise WeatherError("Open-Meteo fetch failed") from err
        self._cache[model] = forecast
        self.diagnostics[model] = diagnostics
        return forecast
