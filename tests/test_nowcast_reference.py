"""Momentary AC observations need momentary references, not hourly means.

All sites/weather/meters here are fictional. Independent minute-midpoint
radiation/production supplies synthetic truth; no test asserts real accuracy.
"""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from statistics import fmean
from types import SimpleNamespace

import pandas as pd
import pvlib
import pytest

from custom_components.adaptive_solar.core import engine as engine_module
from custom_components.adaptive_solar.core import physics as physics_module
from custom_components.adaptive_solar.core.engine import ForecastEngine, _instantaneous_reference
from custom_components.adaptive_solar.core.models import InverterConfig, Observation, SiteConfig, StringConfig, WeatherForecast, WeatherPoint
from custom_components.adaptive_solar.core.physics import instantaneous_weather, inverter_power

UTC = timezone.utc
MINUTE = timedelta(minutes=1)


def site(models=("a",), cap=4.5):
    return SiteConfig(50, 10, "Europe/Berlin", (StringConfig("fictional_south", "i", 5, 30, 180),),
                      (InverterConfig("i", cap),), weather_models=models, forecast_days=1)


@lru_cache(maxsize=12)
def case(hour=5, minute=5, scale=1.0):
    issued = datetime(2026, 6, 21, hour, minute, tzinfo=UTC)
    start = issued.replace(minute=0)
    fine_start = start - timedelta(hours=1)
    config = site()
    location = pvlib.location.Location(config.latitude, config.longitude, tz="UTC")
    starts = [fine_start + index * MINUTE for index in range(300)]
    clear = location.get_clearsky(pd.DatetimeIndex([time + MINUTE / 2 for time in starts]), model="ineichen")
    fine = tuple(WeatherPoint(time, time + MINUTE, float(row.ghi), float(row.dni), float(row.dhi), 20, 2, 0)
                 for time, (_, row) in zip(starts, clear.iterrows(), strict=True))
    truth = tuple((point.start, point.end, inverter_power(config, point)["i"]) for point in fine)
    hourly = []
    for offset in range(5):
        values = fine[offset * 60:(offset + 1) * 60]
        hourly.append(WeatherPoint(values[0].start, values[-1].end,
            fmean(point.ghi_w_m2 for point in values) * scale,
            fmean(point.dni_w_m2 for point in values) * scale,
            fmean(point.dhi_w_m2 for point in values) * scale, 20, 2, 0))
    # This instant uses the same physical generative process as truth, without
    # using the reference helper, its quadrature or a forecast point's power.
    raw = location.get_clearsky(pd.DatetimeIndex([issued]), model="ineichen").iloc[0]
    instant_weather = WeatherPoint(issued - MINUTE / 2, issued + MINUTE / 2,
                                  float(raw.ghi), float(raw.dni), float(raw.dhi), 20, 2, 0)
    instant_power = inverter_power(config, instant_weather)["i"]
    return config, issued, tuple(hourly), fine, truth, instant_weather, instant_power


def source(points, issued, model="a"):
    return WeatherForecast(model, issued, tuple(points))


def truth_kwh(truth, start, end):
    return sum(power * (min(stop, end) - max(begin, start)).total_seconds() / 3_600_000
               for begin, stop, power in truth if begin < end and stop > start)


@pytest.mark.parametrize("hour,minute", [(5, 5), (5, 55), (15, 5), (15, 55)])
def test_clear_sky_solar_motion_does_not_create_false_power_nowcast(hour, minute):
    config, issued, hourly, _, truth, _, actual = case(hour, minute)
    forecast = source(hourly, issued)
    observed = Observation(issued, "i", power_w=actual)
    reference, status = _instantaneous_reference(config, {"a": forecast}, ("a",), observed, issued, (observed,), None, None, {})
    assert status == "usable:instantaneous_physics_approximation"
    assert reference.power_w == pytest.approx(actual, abs=0.02)
    baseline = ForecastEngine(config).forecast((forecast,), issued)
    result = ForecastEngine(config).forecast((forecast,), issued, (observed,))
    start = issued.replace(minute=0) + timedelta(hours=1)
    stop = start + timedelta(hours=1)
    assert abs(result.energy_kwh(start, stop) - baseline.energy_kwh(start, stop)) * 1000 < 0.01
    # The reference changes no public interval boundaries, baseline or features.
    assert [(p.start, p.end, p.baseline_w, p.features) for p in result.points] == [
        (p.start, p.end, p.baseline_w, p.features) for p in baseline.points]
    assert truth_kwh(truth, start, stop) > 0


@pytest.mark.parametrize("hour,minute", [(5, 5), (5, 55), (15, 5), (15, 55)])
def test_real_persistent_weather_bias_still_gets_observational_improvement(hour, minute):
    config, issued, hourly, _, truth, _, actual = case(hour, minute, 0.7)
    forecast = source(hourly, issued)
    engine = ForecastEngine(config)
    baseline = engine.forecast((forecast,), issued)
    result = engine.forecast((forecast,), issued, (Observation(issued, "i", power_w=actual),))
    start = issued.replace(minute=0) + timedelta(hours=1)
    stop = start + timedelta(hours=1)
    true = truth_kwh(truth, start, stop)
    assert abs(result.energy_kwh(start, stop) - true) < abs(baseline.energy_kwh(start, stop) - true)
    assert result.model_status["power_nowcast:i"].startswith("usable")


@pytest.mark.parametrize("state", ["cold", "active"])
def test_reference_includes_same_learner_correction_without_counting_it_twice(state):
    config, issued, hourly, _, _, _, actual = case(15, 55)
    class Learner:
        def predict(self, inverter_id, features, baseline_w, cap_w):
            if state == "cold":
                return SimpleNamespace(power_w=baseline_w, lower_w=None, upper_w=None, status="physics_cold_start")
            return SimpleNamespace(power_w=baseline_w * 0.8, lower_w=None, upper_w=None, status="residual_no_uncertainty")
    learner = Learner()
    observed = Observation(issued, "i", power_w=actual * (0.8 if state == "active" else 1))
    engine = ForecastEngine(config)
    forecasts = (source(hourly, issued),)
    expected = engine.forecast(forecasts, issued, learner=learner)
    result = engine.forecast(forecasts, issued, (observed,), learner)
    assert [point.power_w for point in result.points] == pytest.approx([point.power_w for point in expected.points], abs=0.02)


def test_contemporaneous_ghi_explaining_weather_bias_is_not_repeated_by_power_nowcast():
    config, issued, hourly, _, _, instant_weather, actual = case(10, 5, 0.7)
    ghi = Observation(issued, "i", ghi_w_m2=instant_weather.ghi_w_m2)
    power = Observation(issued, "i", power_w=actual)
    engine = ForecastEngine(config)
    forecasts = (source(hourly, issued),)
    expected = engine.forecast(forecasts, issued, (ghi,))
    result = engine.forecast(forecasts, issued, (replace(ghi, power_w=actual),))
    partial = result.points[1]
    assert partial.start < issued + timedelta(minutes=90) < partial.end
    assert partial.features["ghi_regime"] == 1
    assert result.points[2].features["ghi_regime"] == 0
    power_only = engine.forecast(forecasts, issued, (power,))
    for point, ghi_point, nwp_point in zip(result.points, expected.points, power_only.points, strict=True):
        if point.features["ghi_regime"]:
            assert point.power_w == pytest.approx(ghi_point.power_w, abs=0.02)
        else:
            # Outside the GHI window the unscaled target uses an unscaled
            # instant reference; power may still correct within its own 3h.
            assert point == nwp_point
    assert result.points[2].power_w > expected.points[2].power_w
    assert result.model_status["power_nowcast:i"].startswith("usable")


def test_newer_ghi_does_not_backfill_an_earlier_ac_measurement():
    config, issued, hourly, _, _, instant_weather, actual = case(10, 5, 0.7)
    ghi = Observation(issued, "i", ghi_w_m2=instant_weather.ghi_w_m2)
    earlier_power = Observation(issued - timedelta(seconds=1), "i", power_w=actual)
    forecasts = (source(hourly, issued),)
    expected = ForecastEngine(config).forecast(forecasts, issued, (ghi,))
    result = ForecastEngine(config).forecast(forecasts, issued, (ghi, earlier_power))
    power_only = ForecastEngine(config).forecast(forecasts, issued, (earlier_power,))
    for point, ghi_point, nwp_point in zip(result.points, expected.points, power_only.points, strict=True):
        assert point == (ghi_point if point.features["ghi_regime"] else nwp_point)
    assert "ignored:ghi_newer_than_power" in result.model_status["power_nowcast:i"]


def test_fresh_observation_in_just_ended_original_hour_remains_usable():
    config, observed_at, hourly, _, _, _, actual = case(5, 55, 0.7)
    issued = observed_at.replace(minute=0) + timedelta(hours=1, minutes=1)
    forecasts = (source(hourly, issued),)
    observed = Observation(observed_at, "i", power_w=actual)
    baseline = ForecastEngine(config).forecast(forecasts, issued)
    result = ForecastEngine(config).forecast(forecasts, issued, (observed,))
    assert all(point.start >= issued.replace(minute=0) for point in result.points)
    assert result.points[0].power_w > baseline.points[0].power_w
    assert result.model_status["power_nowcast:i"].startswith("usable")


@pytest.mark.parametrize("minutes", [16, 30, 60])
def test_original_weather_rasters_and_ensemble_do_not_create_instant_residual(minutes):
    config, issued, _, fine, _, _, actual = case(5, 55)
    models = ("a", "b")
    config = replace(config, weather_models=models)
    arms = []
    for model, width in zip(models, (minutes, 60), strict=True):
        pieces = []
        for index in range(0, 240, width):
            values = fine[index:index + width]
            pieces.append(WeatherPoint(values[0].start, values[-1].end,
                fmean(p.ghi_w_m2 for p in values), fmean(p.dni_w_m2 for p in values),
                fmean(p.dhi_w_m2 for p in values), 20, 2, 0))
        arms.append(source(pieces, issued, model))
    expected = ForecastEngine(config).forecast(arms, issued)
    result = ForecastEngine(config).forecast(arms, issued, (Observation(issued, "i", power_w=actual),))
    assert [p.power_w for p in result.points] == pytest.approx([p.power_w for p in expected.points], abs=0.02)
    assert [(p.start, p.end) for p in result.points] == [(p.start, p.end) for p in expected.points]


@pytest.mark.parametrize("problem", ["gap", "final_endpoint", "missing_member"])
def test_no_instant_reference_is_extrapolated_through_gap_or_end(problem):
    config, issued, hourly, _, _, _, actual = case(10, 5)
    after = tuple(point for point in hourly if point.start > issued)
    if problem == "gap":
        arms = (source(after, issued),)
    elif problem == "final_endpoint":
        ended = replace(hourly[1], end=issued)
        arms = (source((ended, *after), issued),)
    else:
        config = replace(config, weather_models=("a", "b"))
        arms = (source(hourly, issued), source(after, issued, "b"))
    engine = ForecastEngine(config)
    expected = engine.forecast(arms, issued)
    result = engine.forecast(arms, issued, (Observation(issued, "i", power_w=actual),))
    if problem == "missing_member":
        # Future b-containing intervals must not silently reuse only model a.
        starts = {point.start for point in after}
        assert [p.power_w for p in result.points if p.start in starts] == [p.power_w for p in expected.points if p.start in starts]
    else:
        assert result.points == expected.points
    assert "ignored:no_original_weather_support" in result.model_status["power_nowcast:i"]


@pytest.mark.parametrize("offset,curtailed", [(timedelta(minutes=-16), False), (timedelta(seconds=1), False), (timedelta(0), True)])
def test_stale_future_and_curtailed_production_do_not_drive_new_reference(offset, curtailed):
    config, issued, hourly, _, _, _, actual = case(15, 5, 0.7)
    forecasts = (source(hourly, issued),)
    engine = ForecastEngine(config)
    expected = engine.forecast(forecasts, issued)
    result = engine.forecast(forecasts, issued, (Observation(issued + offset, "i", power_w=actual, curtailed=curtailed),))
    assert result.points == expected.points


@pytest.mark.parametrize("at", [datetime(2026, 3, 29, 1, 30, tzinfo=UTC), datetime(2026, 10, 25, 0, 30, tzinfo=UTC), datetime(2026, 10, 25, 1, 30, tzinfo=UTC)])
def test_dst_nights_do_not_turn_a_real_utc_observation_into_daytime_reference(at):
    config = site()
    point = WeatherPoint(at.replace(minute=0), at.replace(minute=0) + timedelta(hours=1), 0, 0, 0, 20, 2, 0)
    assert instantaneous_weather(config, point, at) is None
    forecasts = (source((point,), at),)
    expected = ForecastEngine(config).forecast(forecasts, at)
    result = ForecastEngine(config).forecast(forecasts, at, (Observation(at, "i", power_w=500),))
    assert result.points == expected.points
    assert all(p.power_w == 0 for p in result.points)


def test_shared_inverter_cap_applies_after_string_sum_and_after_learner_reference():
    config, issued, hourly, _, _, _, _ = case(10, 5)
    config = replace(config, strings=(StringConfig("east", "i", 5, 30, 90), StringConfig("west", "i", 5, 30, 270)), inverters=(InverterConfig("i", 0.5),))
    forecasts = (source(hourly, issued),)
    class Learner:
        def predict(self, *args):
            return SimpleNamespace(power_w=9000, lower_w=8000, upper_w=10000, status="active")
    result = ForecastEngine(config).forecast(forecasts, issued, (Observation(issued, "i", power_w=500),), Learner())
    assert all(0 <= p.power_w <= 500 for p in result.points)
    assert result.points[0].power_w == 500


def test_missing_local_pvlib_climatology_only_disables_optional_reference(monkeypatch):
    config, issued, hourly, _, _, _, actual = case(15, 55)
    forecasts = (source(hourly, issued),)
    expected = ForecastEngine(config).forecast(forecasts, issued)
    def missing(*args):
        raise OSError("bundled climatology unavailable")
    monkeypatch.setattr(physics_module, "_clear_components", missing)
    result = ForecastEngine(config).forecast(forecasts, issued, (Observation(issued, "i", power_w=actual),))
    assert result.points == expected.points
    assert result.model_status["power_nowcast:i"] == "ignored:no_instantaneous_shape"


def test_weak_instantaneous_baseline_below_scaled_10w_gate_is_not_corrected():
    config, issued, hourly, _, _, _, _ = case(15, 55, 0.001)
    forecasts = (source(hourly, issued),)
    expected = ForecastEngine(config).forecast(forecasts, issued)
    result = ForecastEngine(config).forecast(forecasts, issued, (Observation(issued, "i", power_w=200),))
    assert result.points == expected.points
    assert result.model_status["power_nowcast:i"] == "ignored:weak_instantaneous_reference"


def test_running_copy_is_the_actual_import_source():
    assert Path(engine_module.__file__).resolve().is_relative_to(Path(__file__).resolve().parents[1])


def test_real_learner_lead_range_cannot_double_apply_an_active_target_plant_bias():
    from custom_components.adaptive_solar.core.learning import ResidualLearner
    from custom_components.adaptive_solar.core.models import TrainingSample
    first = datetime(2025, 4, 1, tzinfo=UTC)
    samples = []
    for day in range(50):
        for hour in range(6, 18):
            start = first + timedelta(days=day, hours=hour)
            issued = start - timedelta(hours=1)
            baseline = 1500.0 + hour * 40
            features = {"baseline_w": baseline, "sun_elevation_deg": 40.0,
                "sun_azimuth_sin": 0.0, "sun_azimuth_cos": -1.0,
                "day_of_year_sin": 0.5, "day_of_year_cos": 0.5,
                "temperature_c": 20.0, "wind_m_s": 2.0, "cloud_cover_pct": 0.0, "lead_hours": 1.5}
            samples.append(TrainingSample(issued, start, start + timedelta(hours=1),
                start + timedelta(hours=1, minutes=1), "i", baseline, baseline - 250, features))
    learner = ResidualLearner().fit(samples, first + timedelta(days=51))
    report = learner.status["i"]["lead_bins"]["0-6h"]
    assert report["state"] == "active"
    assert report["supported_lead_min_hours"] == report["supported_lead_max_hours"] == 1.5
    probe = dict(samples[0].features)
    assert learner.predict("i", {**probe, "lead_hours": 0}, probe["baseline_w"], 4500).status == "physics_lead_outside_validated_range"
    assert learner.predict("i", probe, probe["baseline_w"], 4500).status.startswith("residual_")
    config, issued, hourly, _, _, _, actual = case(10, 0)
    forecasts = (source(hourly, issued),)
    engine = ForecastEngine(config)
    baseline = engine.forecast(forecasts, issued, learner=learner)
    result = engine.forecast(forecasts, issued, (Observation(issued, "i", power_w=actual - 250),), learner)
    active_target = issued + timedelta(hours=1)
    expected = next(point for point in baseline.points if point.start == active_target)
    corrected = next(point for point in result.points if point.start == active_target)
    assert corrected == expected  # Its learned -250 W must not be added twice.
    assert result.points[0].power_w < baseline.points[0].power_w  # Physics/physics remains useful.
    assert "ignored:incomparable_learning_support" in result.model_status["power_nowcast:i"]
    assert "usable:instantaneous_physics_approximation" in result.model_status["power_nowcast:i"]


def test_stable_partial_beam_shading_in_nowcast_reference_creates_no_false_residual():
    from custom_components.adaptive_solar.core.physics import solar_position
    from custom_components.adaptive_solar.core.shading import BeamShadeTable

    config, issued, hourly, _, _, instant_weather, _ = case(10, 5)
    sun = solar_position(config, issued)
    table = BeamShadeTable()
    for idx in range(5):
        table.record("i", sun.azimuth_deg, sun.elevation_deg, issued - timedelta(minutes=15 * idx), 0.5)
    shaded_actual = inverter_power(config, instant_weather, beam_shade_factor=0.5)["i"]
    forecast = source(hourly, issued)
    observed = Observation(issued, "i", power_w=shaded_actual)
    reference, status = _instantaneous_reference(
        config, {"a": forecast}, ("a",), observed, issued, (observed,), None, None, {}, table
    )
    assert status == "usable:instantaneous_physics_approximation"
    assert reference.power_w == pytest.approx(shaded_actual, abs=0.05)
    engine = ForecastEngine(config, shading=table)
    baseline = engine.forecast((forecast,), issued)
    with_nowcast = engine.forecast((forecast,), issued, (observed,))
    # Future hours outside the shaded bin are not pulled down by the already-modeled shade factor.
    later = next(p for p in baseline.points if p.start == issued.replace(minute=0) + timedelta(hours=2))
    later_nowcast = next(p for p in with_nowcast.points if p.start == later.start)
    assert later_nowcast.power_w == pytest.approx(later.power_w, abs=0.05)
