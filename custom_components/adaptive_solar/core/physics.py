"""pvlib geometry, transposition, Faiman temperature and PVWatts DC.

The horizon attenuates only direct POA, preserving diffuse and ground radiation.
String DC generation precedes one declared output stage. AC retains the existing
efficiency/AC limit; DC uses only explicit DC-stage losses and one DC output cap.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta
from functools import lru_cache
import math
from zoneinfo import ZoneInfo

import pandas as pd
import pvlib

from .models import HorizonPoint, SiteConfig, StringConfig, WeatherPoint, utc_time


class PhysicsUnavailable(ValueError):
    """A numerical model returned nonfinite data for this supported interval.

    Only this explicit data-quality condition is recoverable as a forecast gap.
    Invalid call contracts and unexpected library/code errors still propagate.
    """


def _finite_physics(value, quantity: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise PhysicsUnavailable(f"nonfinite_{quantity}")
    return number


@dataclass(frozen=True)
class SolarPosition:
    elevation_deg: float
    azimuth_deg: float
    zenith_deg: float


@lru_cache(maxsize=16384)
def _position(latitude: float, longitude: float, time: datetime) -> SolarPosition:
    row = pvlib.solarposition.get_solarposition(pd.DatetimeIndex([time]), latitude, longitude).iloc[0]
    return SolarPosition(*(_finite_physics(row[name], "solar_position")
                           for name in ("apparent_elevation", "azimuth", "apparent_zenith")))


def solar_position(config: SiteConfig, time: datetime) -> SolarPosition:
    return _position(config.latitude, config.longitude, utc_time(time))


@lru_cache(maxsize=4096)
def _daylight_windows(latitude, longitude, timezone, day):
    """SPA daylight pairs around the civil day, including midnight-crossing sun.

    Adjacent dates also support UTC configurations far from the longitude's
    solar timezone. Polar day/night has no sunrise/sunset pair and therefore
    no defined dawn/dusk damping; the neutral factor is used explicitly.
    """
    zone = ZoneInfo(timezone)
    times = pd.DatetimeIndex([datetime.combine(day + timedelta(days=offset), time(12), zone)
                              for offset in (-1, 0, 1)])
    events = pvlib.solarposition.sun_rise_set_transit_spa(times, latitude, longitude)
    windows = []
    for _, row in events.iterrows():
        if pd.isna(row.sunrise) or pd.isna(row.sunset):
            continue
        rise = utc_time(row.sunrise.to_pydatetime(warn=False))
        setting = utc_time(row.sunset.to_pydatetime(warn=False))
        if rise < setting:
            windows.append((rise, setting))
    return tuple(windows)


def damping_factor(config: SiteConfig, string: StringConfig, at: datetime) -> float:
    """Linear sunrise/noon/sunset output damping, independent for every string.

    The factor equals 1-morning at sunrise, 1 at daylight midpoint and
    1-evening at sunset. It is applied after temperature and before the shared
    output cap; it does not scale the meteorological irradiance or temperature.
    """
    if string.damping_morning == 0 and string.damping_evening == 0:
        return 1.0
    at = utc_time(at)
    local_day = at.astimezone(ZoneInfo(config.timezone)).date()
    for rise, setting in _daylight_windows(config.latitude, config.longitude, config.timezone, local_day):
        if rise <= at <= setting:
            noon = rise + (setting - rise) / 2
            if at <= noon:
                return 1 - string.damping_morning * (noon - at) / (noon - rise)
            return 1 - string.damping_evening * (at - noon) / (setting - noon)
    return 1.0



@lru_cache(maxsize=16384)
def _clear_sky_ghi(latitude: float, longitude: float, time: datetime) -> float:
    """Haurwitz is a geometry reference, not a measured clear-sky calibration.

    pvlib's Haurwitz model needs only apparent zenith and returns GHI. It is
    used solely to cancel solar-motion bias in a short-lived cloud multiplier,
    never to invent a measured DNI/DHI decomposition.
    https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.clearsky.haurwitz.html
    """
    sun = _position(latitude, longitude, time)
    if sun.elevation_deg <= 0:
        return 0.0
    result = _finite_physics(pvlib.clearsky.haurwitz(pd.Series([sun.zenith_deg]))["ghi"].iloc[0], "clear_sky_ghi")
    return max(0.0, result)


def clear_sky_ghi(config: SiteConfig, time: datetime) -> float:
    return _clear_sky_ghi(config.latitude, config.longitude, utc_time(time))


@lru_cache(maxsize=2048)
def _clear_sky_ghi_mean(latitude: float, longitude: float, start: datetime, end: datetime) -> float:
    # Four-point Gauss-Legendre quadrature over the ORIGINAL weather interval.
    # Normalized weights integrate a mean, not energy, independent of duration.
    nodes = (-0.8611363115940526, -0.3399810435848563, 0.3399810435848563, 0.8611363115940526)
    weights = (0.3478548451374538, 0.6521451548625461, 0.6521451548625461, 0.3478548451374538)
    midpoint, half = start + (end - start) / 2, (end - start) / 2
    return sum(weight * _clear_sky_ghi(latitude, longitude, midpoint + half * node) for node, weight in zip(nodes, weights, strict=True)) / 2


def clear_sky_ghi_mean(config: SiteConfig, start: datetime, end: datetime) -> float:
    start, end = utc_time(start), utc_time(end)
    if end <= start:
        raise ValueError("clear-sky interval must have positive duration")
    return _clear_sky_ghi_mean(config.latitude, config.longitude, start, end)


@lru_cache(maxsize=4096)
def _clear_components(latitude: float, longitude: float, time: datetime) -> tuple[float, float, float]:
    values = pvlib.location.Location(latitude, longitude, tz="UTC").get_clearsky(
        pd.DatetimeIndex([time]), model="ineichen").iloc[0]
    return tuple(float(values[name]) for name in ("ghi", "dni", "dhi"))


@lru_cache(maxsize=2048)
def _clear_component_means(latitude: float, longitude: float, start: datetime, end: datetime) -> tuple[float, float, float]:
    # Eight-point Gauss-Legendre mean on the ORIGINAL source interval. This
    # geometry/atmosphere reference uses pvlib's bundled Linke-turbidity data
    # (and its h5py dependency), never a network or a new NWP request.
    nodes = (-0.9602898564975363, -0.7966664774136267, -0.5255324099163290, -0.1834346424956498,
              0.1834346424956498, 0.5255324099163290, 0.7966664774136267, 0.9602898564975363)
    weights = (0.1012285362903763, 0.2223810344533745, 0.3137066458778873, 0.3626837833783620,
               0.3626837833783620, 0.3137066458778873, 0.2223810344533745, 0.1012285362903763)
    middle, half = start + (end - start) / 2, (end - start) / 2
    times = pd.DatetimeIndex([middle + half * node for node in nodes])
    values = pvlib.location.Location(latitude, longitude, tz="UTC").get_clearsky(times, model="ineichen")
    return tuple(sum(weight * float(value) for weight, value in zip(weights, values[name], strict=True)) / 2
                 for name in ("ghi", "dni", "dhi"))


def instantaneous_weather(config: SiteConfig, weather: WeatherPoint, at: datetime) -> WeatherPoint | None:
    """Internal instant approximation; never publish it as an interval mean.

    The original NWP inputs remain means. A modeled clear-sky time shape maps
    each component to the covered observation instant. It is not a measured
    DNI/DHI decomposition or proof about intrahour cloud motion. The returned
    proxy retains the ORIGINAL support interval and must only be evaluated by
    inverter_power(..., at=at). Missing support, night, weak/invalid component
    normalization or values outside the weather contract fail closed.
    """
    at = utc_time(at)
    if not weather.start <= at < weather.end:
        return None
    try:
        if solar_position(config, at).elevation_deg <= 0:
            return None
        instantaneous = _clear_components(config.latitude, config.longitude, at)
        means = _clear_component_means(config.latitude, config.longitude, weather.start, weather.end)
    except (PhysicsUnavailable, OSError):
        # Missing bundled climatology or an invalid shape must not remove the
        # interval forecast. Unexpected code/library errors still propagate.
        return None
    components = []
    for original, instant, mean, cap in zip((weather.ghi_w_m2, weather.dni_w_m2, weather.dhi_w_m2),
                                            instantaneous, means, (2500, 2000, 2500), strict=True):
        if not math.isfinite(instant) or not math.isfinite(mean) or instant < 0 or mean < 0:
            return None
        if original == 0:
            value = 0.0
        elif mean < 1.0:
            return None
        else:
            value = original * instant / mean
        if not math.isfinite(value) or not 0 <= value <= cap:
            return None
        components.append(value)
    return replace(weather, ghi_w_m2=components[0], dni_w_m2=components[1], dhi_w_m2=components[2])

def horizon_at(horizon: tuple[HorizonPoint, ...], azimuth_deg: float) -> tuple[float, float]:
    """Circular linear interpolation of elevation and partial beam transmission."""
    if not horizon:
        return 0.0, 1.0
    if len(horizon) == 1:
        return horizon[0].elevation_deg, horizon[0].beam_transmission
    points = sorted(horizon, key=lambda p: p.azimuth_deg)
    azimuth = azimuth_deg % 360
    index = bisect_right([p.azimuth_deg for p in points], azimuth)
    left, right = points[index - 1], points[index % len(points)]
    left_az, right_az = left.azimuth_deg, right.azimuth_deg
    if index == 0:
        left_az -= 360
    if index == len(points):
        right_az += 360
    weight = (azimuth - left_az) / (right_az - left_az)
    return (left.elevation_deg + weight * (right.elevation_deg - left.elevation_deg),
            left.beam_transmission + weight * (right.beam_transmission - left.beam_transmission))


def string_dc_power(config: SiteConfig, string: StringConfig, weather: WeatherPoint, *, at: datetime | None = None) -> float:
    midpoint = weather.start + (weather.end - weather.start) / 2 if at is None else utc_time(at)
    if not weather.start <= midpoint < weather.end:
        raise ValueError("physical evaluation instant must be inside original weather support")
    sun = solar_position(config, midpoint)
    if sun.elevation_deg <= 0 or weather.ghi_w_m2 + weather.dni_w_m2 + weather.dhi_w_m2 == 0:
        return 0.0
    extra = _finite_physics(pvlib.irradiance.get_extra_radiation(midpoint), "extra_radiation")
    poa = pvlib.irradiance.get_total_irradiance(
        surface_tilt=string.tilt_deg, surface_azimuth=string.azimuth_deg,
        solar_zenith=sun.zenith_deg, solar_azimuth=sun.azimuth_deg,
        dni=weather.dni_w_m2, ghi=weather.ghi_w_m2, dhi=weather.dhi_w_m2,
        dni_extra=extra, model="haydavies", albedo=0.2,
    )
    horizon_elevation, transmission = horizon_at(string.horizon, sun.azimuth_deg)
    direct = _finite_physics(poa["poa_direct"], "poa_direct")
    if sun.elevation_deg <= horizon_elevation:
        direct *= transmission
    irradiance = max(0.0, _finite_physics(direct + _finite_physics(poa["poa_diffuse"], "poa_diffuse"), "poa_total"))
    module_temperature = _finite_physics(pvlib.temperature.faiman(irradiance, weather.temperature_c, weather.wind_m_s), "module_temperature")
    power = float(pvlib.pvsystem.pvwatts_dc(irradiance, module_temperature,
        string.peak_kw * 1000, string.temperature_coefficient)) * (1 - string.loss_fraction)
    return max(0.0, _finite_physics(power * damping_factor(config, string, midpoint), "string_dc_power"))


def inverter_power(config: SiteConfig, weather: WeatherPoint, *, at: datetime | None = None,
                   inverter_id: str | None = None) -> dict[str, float]:
    """Power at each declared AC or DC output, after summing all its strings.

    The historical function name remains for compatibility. A DC stage models
    its configured output boundary, without an AC conversion, battery flow or
    an operational curtailment simulation. Shared-MPPT electrical mismatch is
    not identified from aggregate meters or explicitly modeled by this sum.
    Selecting inverter_id evaluates only that stage's strings; unrelated
    numerical failures cannot suppress its output. None retains the all-stage API.
    """
    inverters = tuple(inv for inv in config.inverters if inverter_id is None or inv.id == inverter_id)
    if not inverters:
        raise ValueError("unknown output stage")
    dc = {inverter.id: 0.0 for inverter in inverters}
    for string in config.strings:
        if string.inverter_id in dc:
            dc[string.inverter_id] += string_dc_power(config, string, weather, at=at)
    outputs = {}
    for inverter in inverters:
        # Check before multiplication/clip: min(cap, NaN) can return the cap,
        # and an invalid sum must never become apparently valid generation.
        _finite_physics(dc[inverter.id], "string_dc_sum")
        if inverter.output_type == "ac":
            # Preserve the old multiplication/clip order and default numbers.
            power = dc[inverter.id] * inverter.efficiency
        else:
            power = dc[inverter.id] * (1 - inverter.dc_loss_fraction)
        outputs[inverter.id] = min(inverter.output_cap_w, _finite_physics(power, "output_power"))
    return outputs
