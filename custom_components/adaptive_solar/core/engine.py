"""Interval-preserving multi-weather ensemble, guarded ML and short nowcast."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta
from math import cos, exp, pi, sin
from statistics import fmean
from zoneinfo import ZoneInfo

from .models import (ForecastPoint, ForecastResult, Observation, SiteConfig,
                     WeatherForecast, finite_number, midpoint_lead_hours, utc_time)
from .physics import PhysicsUnavailable, clear_sky_ghi, clear_sky_ghi_mean, instantaneous_weather, inverter_power, solar_position
from .shading import (
     MAX_SHADE_PAIR_SECONDS,
     MIN_SHADE_CLEAR_SKY_W_M2,
     MIN_SHADE_ELEVATION_DEG,
     BeamShadeTable,
)

OBSERVATION_MAX_AGE = timedelta(minutes=15)
LOCAL_WEATHER_HORIZON_HOURS = 2.0
NOWCAST_HORIZON_HOURS = 3.0
NOWCAST_DECAY_HOURS = 0.75
WEATHER_MAX_AGE = timedelta(hours=12)
GHI_MAX_AGE = timedelta(minutes=5)
GHI_HORIZON = timedelta(minutes=90)
GHI_DECAY_SECONDS = 30 * 60


@dataclass(frozen=True)
class InstantReference:
    """Internal instantaneous approximation, never an archived interval mean."""
    baseline_w: float
    power_w: float
    features: dict[str, float]
    learner_status: str


def _prediction(learner, inverter_id, features, baseline, cap):
    """Use identical learner validation for published means and instant refs."""
    if learner is None or baseline <= 0:
        return baseline, None, None, "physics"
    try:
        prediction = learner.predict(inverter_id, dict(features), baseline, cap)
        prediction_status = str(prediction.status)
        proposed = finite_number(prediction.power_w, "ML power", 0)
        lower, upper = prediction.lower_w, prediction.upper_w
        if (lower is None) != (upper is None):
            raise ValueError("incomplete ML interval")
        if lower is not None:
            lower = finite_number(lower, "ML lower", 0)
            upper = finite_number(upper, "ML upper", 0)
            if not lower <= proposed <= upper:
                raise ValueError("invalid ML interval")
        if prediction_status.startswith("physics") or "rejected" in prediction_status:
            proposed, lower, upper = baseline, None, None
        if lower is None:
            prediction_status = _without_uncertainty(prediction_status)
        return min(cap, proposed), None if lower is None else min(cap, lower), None if upper is None else min(cap, upper), prediction_status
    except Exception:
        # A failing optional learner does not remove the physical forecast.
        # BaseException (cancel/interrupt) still propagates.
        return baseline, None, None, "physics:invalid_ml"


def _scale_irradiance(weather, gain):
    caps = ((2500, weather.ghi_w_m2), (2000, weather.dni_w_m2), (2500, weather.dhi_w_m2))
    gain = min([gain, *(cap / value for cap, value in caps if value > 0)])
    return replace(weather, ghi_w_m2=weather.ghi_w_m2 * gain,
                   dni_w_m2=weather.dni_w_m2 * gain, dhi_w_m2=weather.dhi_w_m2 * gain), gain


def _without_uncertainty(status):
    return "residual_no_uncertainty" if status == "residual_empirical_calibration" else status


def _physical_members(config, members, inverter_id, start, end, status, gains=None, weight=0.0,
                      beam_shade_factor=1.0):
    """Only this stage can lose a numerical member; never evaluate its peers."""
    result = []
    for model, point in members:
        adjusted, gain = (point, None) if gains is None else _scale_irradiance(point, 1 + (gains[model] - 1) * weight)
        try:
            power = inverter_power(
                config, adjusted, inverter_id=inverter_id, beam_shade_factor=beam_shade_factor
            )[inverter_id]
        except PhysicsUnavailable as exc:
            status[f"physics:{model}:{inverter_id}:{start.isoformat()}/{end.isoformat()}"] = f"unavailable:{exc}"
            continue
        result.append((model, adjusted, power, gain))
    return result


def _instantaneous_member_proxies(config, forecasts, models, at, fresh, ghi_observation, ghi_gains,
                                  *, allow_paired_future_ghi=False, require_unclipped_ghi=False):
    use_ghi = ghi_observation is not None and bool(models) and all(model in ghi_gains for model in models)
    if use_ghi and ghi_observation.time > at and not allow_paired_future_ghi:
        return None, None, "ignored:ghi_newer_than_power"
    member_weather, gains = [], []
    for model in models:
        source = next((point for point in forecasts[model].points if point.start <= at < point.end), None)
        if source is None:
            return None, None, "ignored:no_original_weather_support"
        proxy = instantaneous_weather(config, source, at)
        if proxy is None:
            return None, None, "ignored:no_instantaneous_shape"
        for key in ("temperature_c", "wind_m_s"):
            value = next((getattr(obs, key) for obs in fresh if obs.time <= at and getattr(obs, key) is not None), None)
            if value is not None:
                proxy = replace(proxy, **{key: value})
        if use_ghi:
            ghi_time = ghi_observation.time
            ghi_source = next((point for point in forecasts[model].points if point.start <= ghi_time < point.end), None)
            ghi_proxy = proxy if ghi_time == at else (
                None if ghi_source is None else instantaneous_weather(config, ghi_source, ghi_time))
            if ghi_proxy is None or ghi_proxy.ghi_w_m2 < 50:
                return None, None, "ignored:no_matching_ghi_reference"
            # The existing public GHI path uses a Haurwitz hourly normalization.
            # This instant proxy uses component-wise Ineichen shapes. Reusing
            # the numerical hourly factor would mix the two geometries. Use
            # the SAME measured GHI against this proxy's GHI instead.
            measured_gain = ghi_observation.ghi_w_m2 / ghi_proxy.ghi_w_m2
            full_gain = max(0.35, min(1.65, measured_gain))
            if require_unclipped_ghi and full_gain != measured_gain:
                return None, None, "ignored:clipped_ghi_reference"
            age = max(0.0, (at - ghi_time).total_seconds()) if allow_paired_future_ghi else (at - ghi_time).total_seconds()
            gain = 1 + (full_gain - 1) * exp(-age / GHI_DECAY_SECONDS)
            proxy, applied_gain = _scale_irradiance(proxy, gain)
            if require_unclipped_ghi and applied_gain != gain:
                return None, None, "ignored:clipped_ghi_reference"
            gains.append(applied_gain)
        member_weather.append(proxy)
    if not member_weather:
        return None, None, "ignored:no_reference_members"
    return member_weather, gains, None


def _instantaneous_reference(config, forecasts, models, observation, issued_at, fresh, learner,
                             ghi_observation, ghi_gains, shading: BeamShadeTable | None = None):
    """Match a measured output instant with a same-stage instant approximation.

    Every member of the published interval's ensemble must have ORIGINAL
    source coverage at the observation time. No neighboring hour or changed
    cohort fills a gap. GHI uses its full contemporaneous value against the
    SAME instantaneous proxy; averaged future-hour gains cannot explain a power
    instant. A newer GHI cannot be applied backwards to an older power reading.
    """
    at = observation.time
    member_weather, gains, error = _instantaneous_member_proxies(
        config, forecasts, models, at, fresh, ghi_observation, ghi_gains
    )
    if member_weather is None:
        return None, error
    try:
        sun = solar_position(config, at)
        shade_factor = 1.0 if shading is None else shading.transmittance(
            observation.inverter_id, sun.azimuth_deg, sun.elevation_deg
        )
        member_powers = [
            inverter_power(
                config, proxy, at=at, inverter_id=observation.inverter_id, beam_shade_factor=shade_factor
            )
            for proxy in member_weather
        ]
    except PhysicsUnavailable:
        return None, "ignored:nonfinite_physics"
    baseline = fmean(value[observation.inverter_id] for value in member_powers)
    inverter = next(value for value in config.inverters if value.id == observation.inverter_id)
    if baseline <= max(10.0, inverter.output_cap_w * 0.002):
        return None, "ignored:weak_instantaneous_reference"
    season = 2 * pi * at.astimezone(ZoneInfo(config.timezone)).timetuple().tm_yday / 365.2425
    features = {"baseline_w": baseline, "sun_elevation_deg": sun.elevation_deg,
        "sun_azimuth_deg": sun.azimuth_deg,
        "sun_azimuth_sin": sin(sun.azimuth_deg * pi / 180), "sun_azimuth_cos": cos(sun.azimuth_deg * pi / 180),
        "day_of_year_sin": sin(season), "day_of_year_cos": cos(season),
        "temperature_c": fmean(point.temperature_c for point in member_weather),
        "wind_m_s": fmean(point.wind_m_s for point in member_weather),
        "cloud_cover_pct": fmean(point.cloud_cover_pct for point in member_weather),
        "lead_hours": max(0.0, (at - issued_at).total_seconds() / 3600),
        "ghi_regime": 1.0 if gains else 0.0,
        "ghi_nowcast_gain": fmean(gains) if gains else 1.0,
        "ghi_observation_age_seconds": (at - ghi_observation.time).total_seconds() if gains else 0.0,
        "beam_shade_factor": float(shade_factor),
        "output_cap_w": float(inverter.output_cap_w)}
    if gains:
        features.update({"ghi_observation_w_m2": ghi_observation.ghi_w_m2,
            "ghi_observation_age_seconds": (at - ghi_observation.time).total_seconds(),
            "ghi_nowcast_gain": fmean(gains)})
    power, _, _, learner_status = _prediction(learner, inverter.id, features, baseline, inverter.output_cap_w)
    return InstantReference(baseline, power, features, learner_status), "usable:instantaneous_physics_approximation"


def shade_reference_powers(config: SiteConfig, forecasts, issued_at: datetime,
                           inverter_id: str, at: datetime, observations=()) -> tuple[float, float] | None:
    """Compute unshaded (P0, P1) at `at` using the stage's Nowcast reference cohort and proxy."""
    issued_at = utc_time(issued_at, "issued_at")
    at = utc_time(at, "at")
    latest = {}
    for forecast in forecasts:
        if not isinstance(forecast, WeatherForecast) or forecast.model not in config.weather_models:
            continue
        age = issued_at - forecast.issued_at
        if age < timedelta(0) or age > WEATHER_MAX_AGE:
            continue
        if forecast.model not in latest or forecast.issued_at > latest[forecast.model].issued_at:
            latest[forecast.model] = forecast
    if not latest:
        return None
    observations = tuple(observations)
    inverter_ids = {inv.id for inv in config.inverters}
    if inverter_id not in inverter_ids:
        return None
    fresh = [
        obs for obs in observations
        if isinstance(obs, Observation) and obs.inverter_id in inverter_ids
        and timedelta(0) <= issued_at - obs.time <= OBSERVATION_MAX_AGE
    ]
    fresh.sort(key=lambda o: o.time, reverse=True)
    ghi_candidates = [
        obs for obs in observations
        if isinstance(obs, Observation)
        and obs.ghi_w_m2 is not None
        and obs.inverter_id in inverter_ids
        and timedelta(0) <= issued_at - obs.time <= GHI_MAX_AGE
    ]
    if not ghi_candidates:
        return None
    shade_ghi_obs = max(ghi_candidates, key=lambda obs: obs.time)
    if len({obs.ghi_w_m2 for obs in ghi_candidates if obs.time == shade_ghi_obs.time}) > 1:
        return None
    if abs((at - shade_ghi_obs.time).total_seconds()) > MAX_SHADE_PAIR_SECONDS:
        return None
    try:
        at_sun = solar_position(config, at)
        at_csky = clear_sky_ghi(config, at)
        ghi_sun = at_sun if shade_ghi_obs.time == at else solar_position(config, shade_ghi_obs.time)
        ghi_csky = at_csky if shade_ghi_obs.time == at else clear_sky_ghi(config, shade_ghi_obs.time)
    except PhysicsUnavailable:
        return None
    if (
        at_sun.elevation_deg < MIN_SHADE_ELEVATION_DEG
        or at_csky < MIN_SHADE_CLEAR_SKY_W_M2
        or ghi_sun.elevation_deg < MIN_SHADE_ELEVATION_DEG
        or ghi_csky < MIN_SHADE_CLEAR_SKY_W_M2
    ):
        return None
    ghi_observation, ghi_gains, _ = _irradiance_gains(config, latest, observations, issued_at)
    local = issued_at.astimezone(ZoneInfo(config.timezone))
    last_date = local.date() + timedelta(days=config.forecast_days)
    horizon_end = utc_time(datetime.combine(last_date, time(), ZoneInfo(config.timezone)))
    weather = [
        (model, p) for model, forecast in latest.items() for p in forecast.points
        if p.end > issued_at and p.start < horizon_end
    ]
    boundaries = sorted({t for _, p in weather for t in (max(p.start, issued_at), min(p.end, horizon_end))})
    models = ()
    dummy_status: dict[str, str] = {}
    for start, end in zip(boundaries, boundaries[1:]):
        if end <= issued_at or start >= min(horizon_end, issued_at + timedelta(hours=NOWCAST_HORIZON_HOURS)):
            continue
        members = [(model, p) for model, p in weather if p.start <= start and p.end >= end]
        if not members:
            continue
        midpoint = start + (end - start) / 2
        try:
            sun = solar_position(config, midpoint)
        except PhysicsUnavailable:
            continue
        if sun.elevation_deg <= 0:
            continue
        lead = midpoint_lead_hours(issued_at, start, end)
        prepared = []
        for model, point in members:
            adjusted = replace(point, start=start, end=end)
            if lead < LOCAL_WEATHER_HORIZON_HOURS:
                blend = max(0.0, 1 - lead / LOCAL_WEATHER_HORIZON_HOURS)
                temperature = next((o.temperature_c for o in fresh if o.temperature_c is not None), None)
                wind = next((o.wind_m_s for o in fresh if o.wind_m_s is not None), None)
                adjusted = replace(
                    adjusted,
                    temperature_c=point.temperature_c if temperature is None else point.temperature_c * (1 - blend) + temperature * blend,
                    wind_m_s=point.wind_m_s if wind is None else point.wind_m_s * (1 - blend) + wind * blend,
                )
            prepared.append((model, adjusted))
        evaluated = _physical_members(config, prepared, inverter_id, start, end, dummy_status)
        if not evaluated:
            continue
        weight = (
            _irradiance_weight(start, end, issued_at, ghi_observation.time)
            if ghi_observation is not None and sun.elevation_deg >= 10
            else 0.0
        )
        stage_use_ghi = weight > 0 and all(model in ghi_gains for model, *_ in evaluated)
        if stage_use_ghi:
            evaluated = _physical_members(
                config, [(model, point) for model, point, _, _ in evaluated],
                inverter_id, start, end, dummy_status, ghi_gains, weight,
            )
            if not evaluated:
                continue
        models = tuple(sorted(model for model, *_ in evaluated))
        break
    if not models:
        return None
    shade_ghi_gains = {}
    for model in models:
        ghi_source = next((p for p in latest[model].points if p.start <= shade_ghi_obs.time < p.end), None)
        if ghi_source is None or ghi_source.ghi_w_m2 < 50:
            return None
        try:
            source_mean = clear_sky_ghi_mean(config, ghi_source.start, ghi_source.end)
        except PhysicsUnavailable:
            return None
        if source_mean < MIN_SHADE_CLEAR_SKY_W_M2:
            return None
        shade_ghi_gains[model] = 1.0
    member_weather, gains, _ = _instantaneous_member_proxies(
        config, latest, models, at, fresh,
        shade_ghi_obs,
        shade_ghi_gains,
        allow_paired_future_ghi=True,
        require_unclipped_ghi=True,
    )
    if member_weather is None or not gains or len(gains) != len(models):
        return None
    try:
        p0_values = [
            inverter_power(config, proxy, at=at, inverter_id=inverter_id, beam_shade_factor=0.0)[inverter_id]
            for proxy in member_weather
        ]
        p1_values = [
            inverter_power(config, proxy, at=at, inverter_id=inverter_id, beam_shade_factor=1.0)[inverter_id]
            for proxy in member_weather
        ]
    except PhysicsUnavailable:
        return None
    p0_w = fmean(p0_values)
    p1_w = fmean(p1_values)
    inverter = next(value for value in config.inverters if value.id == inverter_id)
    if p1_w <= max(10.0, inverter.output_cap_w * 0.002):
        return None
    return p0_w, p1_w


def _uses_residual(status):
    return not status.startswith("physics") and "rejected" not in status


def _add_status(status, key, value):
    values = set(status.get(key, "").split(";")) - {""}
    values.add(value)
    status[key] = ";".join(sorted(values))


def _irradiance_gains(config, forecasts, observations, issued_at):
    """Normalize a real GHI instant against each original NWP hour's geometry."""
    candidates = [obs for obs in observations if obs.ghi_w_m2 is not None and obs.inverter_id in {inv.id for inv in config.inverters}]
    fresh = [obs for obs in candidates if timedelta(0) <= issued_at - obs.time <= GHI_MAX_AGE]
    if not fresh:
        reason = "no_observation" if not candidates else "future" if max(obs.time for obs in candidates) > issued_at else "stale"
        return None, {}, f"ignored:{reason}"
    observation = max(fresh, key=lambda obs: obs.time)
    if len({obs.ghi_w_m2 for obs in fresh if obs.time == observation.time}) > 1:
        return None, {}, "ignored:conflicting_measurements"
    try:
        sun = solar_position(config, observation.time)
        instantaneous = clear_sky_ghi(config, observation.time)
    except PhysicsUnavailable:
        return observation, {}, "ignored:nonfinite_reference"
    if sun.elevation_deg < 15 or instantaneous < 150:
        return observation, {}, "ignored:low_sun_or_clear_sky"
    gains = {}
    reasons = set()
    for model, forecast in forecasts.items():
        # Past-but-fresh observation references may end before issued_at. Use
        # the original source interval, never an ensemble-split subinterval.
        reference = next((point for point in forecast.points if point.start <= observation.time < point.end), None)
        if reference is None:
            reasons.add("no_reference_interval")
            continue
        try:
            mean = clear_sky_ghi_mean(config, reference.start, reference.end)
        except PhysicsUnavailable:
            reasons.add("nonfinite_reference")
            continue
        if reference.ghi_w_m2 < 50 or mean < 150:
            reasons.add("weak_reference")
            continue
        ratio = (observation.ghi_w_m2 / instantaneous) / (reference.ghi_w_m2 / mean)
        gains[model] = max(0.35, min(1.65, ratio))
    return observation, gains, "usable:haurwitz_normalized" if gains else "ignored:" + (";".join(sorted(reasons)) or "no_available_weather")


def _irradiance_weight(start, end, issued_at, observed_at):
    """Integrate observation influence only inside its 90-minute window.

    The output interval is clipped at issued_at, so its whole duration is
    genuinely future. A partly overlapping output cell retains its averaged
    correction until it ends; power_at returns that interval mean. Never write
    a remaining-cell mean against the full, already started source interval.
    """
    begin = max(start, issued_at)
    stop = min(end, observed_at + GHI_HORIZON)
    if stop <= begin:
        return 0.0
    a, b = (begin - observed_at).total_seconds(), (stop - observed_at).total_seconds()
    return GHI_DECAY_SECONDS * (exp(-a / GHI_DECAY_SECONDS) - exp(-b / GHI_DECAY_SECONDS)) / (end - start).total_seconds()


class ForecastEngine:
    def __init__(self, config: SiteConfig, shading: BeamShadeTable | None = None):
        self.config = config
        self.shading = shading

    def forecast(self, forecasts, issued_at, observations=(), learner=None,
                 shading: BeamShadeTable | None = None) -> ForecastResult:
        issued_at = utc_time(issued_at, "issued_at")
        config = self.config
        active_shading = self.shading if shading is None else shading
        status = {}
        latest = {}
        for forecast in forecasts:
            if not isinstance(forecast, WeatherForecast):
                raise ValueError("forecasts must contain WeatherForecast")
            if forecast.model not in config.weather_models:
                continue
            age = issued_at - forecast.issued_at
            if age < timedelta(0) or age > WEATHER_MAX_AGE:
                status[f"weather:{forecast.model}"] = "unavailable:future_or_stale"
                continue
            if forecast.model not in latest or forecast.issued_at > latest[forecast.model].issued_at:
                latest[forecast.model] = forecast
        for model in config.weather_models:
            if model in latest:
                status[f"weather:{model}"] = "available"
            else:
                status.setdefault(f"weather:{model}", "unavailable")
        observations = tuple(observations)
        fresh = []
        inverter_ids = {v.id for v in config.inverters}
        for observation in observations:
            if not isinstance(observation, Observation):
                raise ValueError("observations must contain Observation")
            if observation.inverter_id in inverter_ids and timedelta(0) <= issued_at - observation.time <= OBSERVATION_MAX_AGE:
                fresh.append(observation)
        fresh.sort(key=lambda o: o.time, reverse=True)
        ghi_observation, ghi_gains, ghi_status = _irradiance_gains(config, latest, observations, issued_at)
        if config.irradiance_entity_id or any(obs.ghi_w_m2 is not None for obs in observations):
            status["irradiance"] = ghi_status
        local = issued_at.astimezone(ZoneInfo(config.timezone))
        last_date = local.date() + timedelta(days=config.forecast_days)
        horizon_end = utc_time(datetime.combine(last_date, time(), ZoneInfo(config.timezone)))
        weather = [(model, p) for model, forecast in latest.items() for p in forecast.points
                   if p.end > issued_at and p.start < horizon_end]
        # All output support is future support. The current source cell is
        # clipped at the actual issue, while ORIGINAL points remain available
        # to GHI normalization and instantaneous output-reference calculation.
        # A model with a gap contributes nothing; never fill that gap with zero.
        boundaries = sorted({t for _, p in weather for t in (max(p.start, issued_at), min(p.end, horizon_end))})
        rows = []
        row_models = {}
        row_learning = {}
        for start, end in zip(boundaries, boundaries[1:]):
            if end <= issued_at or start >= horizon_end:
                continue
            members = [(model, p) for model, p in weather if p.start <= start and p.end >= end]
            if not members:
                continue
            midpoint = start + (end - start) / 2
            lead = midpoint_lead_hours(issued_at, start, end)
            try:
                sun = solar_position(config, midpoint)
            except PhysicsUnavailable as exc:
                for inverter in config.inverters:
                    for model, _ in members:
                        status[f"physics:{model}:{inverter.id}:{start.isoformat()}/{end.isoformat()}"] = f"unavailable:{exc}"
                continue
            season = 2 * pi * midpoint.astimezone(ZoneInfo(config.timezone)).timetuple().tm_yday / 365.2425
            weight = _irradiance_weight(start, end, issued_at, ghi_observation.time) if ghi_observation is not None and sun.elevation_deg >= 10 else 0.0
            prepared = []
            for model, point in members:
                adjusted = replace(point, start=start, end=end)
                if lead < LOCAL_WEATHER_HORIZON_HOURS:
                    # Current local readings decay to NWP within two hours;
                    # no persisted instantaneous readings enter later days.
                    blend = max(0.0, 1 - lead / LOCAL_WEATHER_HORIZON_HOURS)
                    temperature = next((o.temperature_c for o in fresh if o.temperature_c is not None), None)
                    wind = next((o.wind_m_s for o in fresh if o.wind_m_s is not None), None)
                    adjusted = replace(adjusted,
                        temperature_c=point.temperature_c if temperature is None else point.temperature_c * (1 - blend) + temperature * blend,
                        wind_m_s=point.wind_m_s if wind is None else point.wind_m_s * (1 - blend) + wind * blend)
                prepared.append((model, adjusted))
            for inverter in config.inverters:
                # Determine this stage's valid cohort before choosing its
                # atomic regime. Another stage may retain different members.
                shade_factor = 1.0 if active_shading is None else active_shading.transmittance(
                    inverter.id, sun.azimuth_deg, sun.elevation_deg
                )
                evaluated = _physical_members(
                    config, prepared, inverter.id, start, end, status,
                    beam_shade_factor=shade_factor,
                )
                if not evaluated:
                    continue
                use_ghi = weight > 0 and all(model in ghi_gains for model, *_ in evaluated)
                if weight > 0 and ghi_gains and not use_ghi:
                    status[f"irradiance:{inverter.id}:{start.isoformat()}/{end.isoformat()}"] = "ignored:incomplete_reference_cohort"
                if use_ghi:
                    evaluated = _physical_members(
                        config, [(model, point) for model, point, _, _ in evaluated],
                        inverter.id, start, end, status, ghi_gains, weight,
                        beam_shade_factor=shade_factor,
                    )
                if not evaluated:
                    continue
                available_models = tuple(sorted(model for model, *_ in evaluated))
                member_weather = [point for _, point, _, _ in evaluated]
                applied_gains = [gain for _, _, _, gain in evaluated if gain is not None]
                row_models[start, end, inverter.id] = available_models
                cap = inverter.output_cap_w
                baseline = fmean(power for _, _, power, _ in evaluated)
                features = {"baseline_w": baseline, "sun_elevation_deg": sun.elevation_deg,
                    "sun_azimuth_deg": sun.azimuth_deg,
                    "sun_azimuth_sin": sin(sun.azimuth_deg * pi / 180), "sun_azimuth_cos": cos(sun.azimuth_deg * pi / 180),
                    "day_of_year_sin": sin(season), "day_of_year_cos": cos(season),
                    "temperature_c": fmean(p.temperature_c for p in member_weather),
                    "wind_m_s": fmean(p.wind_m_s for p in member_weather),
                    "cloud_cover_pct": fmean(p.cloud_cover_pct for p in member_weather), "lead_hours": lead,
                    "source_partial_at_issue": float(start == issued_at and any(point.start < issued_at for model, point in members if model in available_models)),
                    "ghi_regime": 1.0 if applied_gains else 0.0,
                    "ghi_nowcast_gain": fmean(applied_gains) if applied_gains else 1.0,
                    "ghi_observation_age_seconds": (issued_at - ghi_observation.time).total_seconds() if applied_gains else 0.0,
                    "beam_shade_factor": float(shade_factor),
                    "output_cap_w": float(cap)}
                if applied_gains:
                    features.update({"ghi_observation_w_m2": ghi_observation.ghi_w_m2,
                        "ghi_observation_age_seconds": (issued_at - ghi_observation.time).total_seconds(),
                        "ghi_nowcast_gain": fmean(applied_gains)})
                power, lower, upper, ml_status = _prediction(
                    learner if sun.elevation_deg > 0 else None, inverter.id, features, baseline, cap)
                if applied_gains:
                    # A matching GHI-regime learner can have empirical bounds.
                    # Conservatively withhold them here: that calibration does
                    # not establish joint coverage for the live observation
                    # path and any downstream power-nowcast correction.
                    lower, upper = None, None
                    ml_status = _without_uncertainty(ml_status)
                row_learning[start, end, inverter.id] = ml_status
                rows.append(ForecastPoint(start, end, inverter.id, baseline, power, lower, upper, features))
        # Correction uses the forecast at the observation's actual time. If
        # that time lacks coverage, no proxy baseline from tomorrow is allowed.
        corrected = []
        reference_cache = {}
        for point in rows:
            inverter = next(v for v in config.inverters if v.id == point.inverter_id)
            cap = inverter.output_cap_w
            own = [o for o in fresh if o.inverter_id == point.inverter_id]
            observation = next((o for o in own if o.power_w is not None), None)
            blocked = any(o.curtailed for o in own)
            reference = None
            if not blocked and observation is not None and max(10.0, cap * 0.002) < observation.power_w <= cap * 1.1 and point.features["sun_elevation_deg"] > 0 and point.start < issued_at + timedelta(hours=NOWCAST_HORIZON_HOURS):
                models = row_models[point.start, point.end, point.inverter_id]
                ghi_regime = bool(point.features["ghi_regime"])
                key = point.inverter_id, models, ghi_regime
                # This reference describes the observation instant. Replacing
                # its full GHI with a future cell's decayed gain invents e(t0).
                if key not in reference_cache:
                    args = (
                        config, latest, models, observation, issued_at, fresh, learner,
                        ghi_observation if ghi_regime else None, ghi_gains if ghi_regime else {},
                    )
                    if active_shading is not None:
                        args = (*args, active_shading)
                    reference_cache[key] = _instantaneous_reference(*args)
                reference, reference_status = reference_cache[key]
                if reference is not None and _uses_residual(reference.learner_status) != _uses_residual(row_learning[point.start, point.end, point.inverter_id]):
                    # A reference at lead=0 often has no validated ML support,
                    # while a later target already uses a learned plant bias.
                    # Adding that bias again via a physics-only reference would
                    # double-correct it. Skip only these mixed-mode targets.
                    reference = None
                    reference_status = "ignored:incomparable_learning_support"
                _add_status(status, f"power_nowcast:{point.inverter_id}", reference_status)
            if reference is not None and reference.baseline_w > max(10.0, cap * 0.002):
                begin = max(point.start, issued_at)
                stop = min(point.end, issued_at + timedelta(hours=NOWCAST_HORIZON_HOURS))
                if stop > begin:
                    # Average exponential over the forecast portion, preserving
                    # the interval-mean contract rather than its midpoint only.
                    age = max(0.0, (issued_at - observation.time).total_seconds() / 3600)
                    a = (begin - issued_at).total_seconds() / 3600
                    b = (stop - issued_at).total_seconds() / 3600
                    duration = (point.end - point.start).total_seconds() / 3600
                    weight = NOWCAST_DECAY_HOURS * (exp(-a / NOWCAST_DECAY_HOURS) - exp(-b / NOWCAST_DECAY_HOURS)) / duration
                    residual = max(-cap * 0.35, min(cap * 0.35, observation.power_w - reference.power_w))
                    correction = 0.5 * exp(-age / NOWCAST_DECAY_HOURS) * residual * weight
                    power = max(0.0, min(cap, point.power_w + correction))
                    # The ML holdout did not calibrate this observation-driven
                    # adjustment; do not present its bounds as calibrated nowcast.
                    if power != point.power_w:
                        point = replace(point, power_w=power, lower_w=None, upper_w=None)
                        key = point.start, point.end, point.inverter_id
                        row_learning[key] = _without_uncertainty(row_learning[key])
            corrected.append(point)
            # Aggregate only final point statuses. An untouched calibrated
            # neighbor may retain calibration; a changed point may not.
            _add_status(status, point.inverter_id, row_learning[point.start, point.end, point.inverter_id])
        return ForecastResult(issued_at, tuple(corrected), status)
