from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
from custom_components.adaptive_solar.core import engine as module
from custom_components.adaptive_solar.core.engine import ForecastEngine
from custom_components.adaptive_solar.core.models import InverterConfig, Observation, SiteConfig, StringConfig, WeatherForecast, WeatherPoint
from custom_components.adaptive_solar.core.physics import PhysicsUnavailable

T = datetime(2026, 6, 21, 10, 5, tzinfo=timezone.utc)
START = T.replace(minute=0)


def config(models=("a", "b"), cap=5):
    return SiteConfig(52, 13, "Europe/Berlin", (StringConfig("s", "i", 5, 30, 180),), (InverterConfig("i", cap),), weather_models=models)


def weather(start=START, ghi=700, hours=1):
    return WeatherPoint(start, start + timedelta(hours=hours), ghi, ghi, 100, 20, 2, 20)


def forecast(model="a", points=None, issue=T):
    return WeatherForecast(model, issue, tuple(points if points is not None else (weather(), weather(START + timedelta(hours=1)), weather(START + timedelta(hours=24)))))


def test_ensemble_does_not_fill_missing_late_model_with_zero():
    engine = ForecastEngine(config())
    a, b = forecast(), forecast("b", (weather(ghi=300),))
    first = engine.forecast((a,), T)
    second = engine.forecast((b,), T)
    merged = engine.forecast((a, b), T)
    assert merged.points[0].power_w == pytest.approx((first.points[0].power_w + second.points[0].power_w) / 2)
    assert merged.points[-1].power_w == first.points[-1].power_w
    assert merged.energy_kwh(START, START + timedelta(hours=25)) is None


def test_different_weather_interval_grids_split_without_overlap():
    result = ForecastEngine(config()).forecast((forecast("a", (weather(hours=1),)),
        forecast("b", (weather(hours=0.5), weather(START + timedelta(minutes=30), hours=0.5)))), T)
    assert len(result.points) == 2
    assert result.points[0].end == result.points[1].start
    assert result.energy_kwh(START, START + timedelta(hours=1)) is None
    assert result.energy_kwh(T, START + timedelta(hours=1)) is not None


def test_future_and_stale_forecasts_and_observations_do_not_enter():
    engine = ForecastEngine(config())
    assert not engine.forecast((forecast(issue=T + timedelta(seconds=1)),), T).points
    assert not engine.forecast((forecast(issue=T - timedelta(hours=13)),), T).points
    baseline = engine.forecast((forecast(),), T)
    for observed in (T + timedelta(seconds=1), T - timedelta(minutes=16)):
        assert engine.forecast((forecast(),), T, (Observation(observed, "i", 50, 50, 10),)).points == baseline.points


def test_local_weather_only_in_short_horizon():
    engine = ForecastEngine(config())
    baseline = engine.forecast((forecast(),), T)
    local = engine.forecast((forecast(),), T, (Observation(T, "i", temperature_c=40, wind_m_s=0),))
    assert local.points[0].baseline_w < baseline.points[0].baseline_w
    assert local.points[-1] == baseline.points[-1]


def test_nowcast_is_short_and_blocked_by_any_recent_curtailment():
    engine = ForecastEngine(config())
    baseline = engine.forecast((forecast(),), T)
    obs = Observation(T, "i", power_w=300)
    corrected = engine.forecast((forecast(),), T, (obs,))
    assert corrected.points[0].power_w < baseline.points[0].power_w
    assert corrected.points[-1] == baseline.points[-1]
    assert engine.forecast((forecast(),), T, (obs, Observation(T - timedelta(minutes=1), "i", curtailed=True))).points == baseline.points
    assert engine.forecast((forecast(),), T, (replace(obs, power_w=0),)).points == baseline.points
    assert engine.forecast((forecast(),), T, (replace(obs, power_w=100000),)).points == baseline.points


def test_nowcast_does_not_use_future_interval_as_observation_reference():
    engine = ForecastEngine(config())
    future = forecast(points=(weather(START + timedelta(hours=1)),))
    assert engine.forecast((future,), T, (Observation(T, "i", 100),)).points == engine.forecast((future,), T).points


@pytest.mark.parametrize("power,lower,upper", [(float("nan"), None, None), (True, None, None), (100, 200, 300), (100, 0, None)])
def test_invalid_learner_prediction_falls_back_to_physics(power, lower, upper):
    class Learner:
        def predict(self, *args):
            return SimpleNamespace(power_w=power, lower_w=lower, upper_w=upper, status="active")
    engine = ForecastEngine(config())
    result = engine.forecast((forecast(),), T, learner=Learner())
    assert result.points == engine.forecast((forecast(),), T).points
    assert result.model_status["i"] == "physics:invalid_ml"


def test_final_ml_and_nowcast_cap_and_night_guard():
    class Learner:
        def predict(self, *args):
            return SimpleNamespace(power_w=9000, lower_w=8000, upper_w=10000, status="active")
    engine = ForecastEngine(config(cap=3))
    result = engine.forecast((forecast(),), T, (Observation(T, "i", 3100),), Learner())
    assert all(0 <= p.power_w <= 3000 and (p.upper_w is None or p.upper_w <= 3000) for p in result.points)
    night = START.replace(hour=23)
    result = engine.forecast((forecast(points=(weather(night),)),), T, learner=Learner())
    assert result.points[0].power_w == 0


def test_rejected_learner_cannot_override_physical_fallback():
    class RejectedLearner:
        def predict(self, *args):
            return SimpleNamespace(power_w=0, lower_w=0, upper_w=0, status="physics_rejected_validation")
    engine = ForecastEngine(config())
    assert engine.forecast((forecast(),), T, learner=RejectedLearner()).points == engine.forecast((forecast(),), T).points


def test_optional_learner_runtime_failure_preserves_physical_forecast():
    class FailedLearner:
        def predict(self, *args):
            raise RuntimeError("optional model unavailable")
    engine = ForecastEngine(config())
    assert engine.forecast((forecast(),), T, learner=FailedLearner()).points == engine.forecast((forecast(),), T).points


def test_available_model_wins_diagnostic_over_ignored_future_issue():
    result = ForecastEngine(config()).forecast((forecast(issue=T + timedelta(minutes=5)), forecast()), T)
    assert result.model_status["weather:a"] == "available"


def test_nowcast_does_not_relabel_ml_bounds_as_calibrated():
    class Learner:
        def predict(self, inverter_id, features, baseline_w, cap_w):
            return SimpleNamespace(power_w=baseline_w, lower_w=max(0, baseline_w - 100), upper_w=min(cap_w, baseline_w + 100), status="residual_empirical_calibration")
    engine = ForecastEngine(config())
    baseline = engine.forecast((forecast(),), T, learner=Learner())
    corrected = engine.forecast((forecast(),), T, (Observation(T, "i", 300),), Learner())
    assert baseline.points[0].lower_w is not None
    assert corrected.points[0].lower_w is None
    assert corrected.points[-1].lower_w == baseline.points[-1].lower_w
    assert corrected.model_status["i"] == "residual_empirical_calibration;residual_no_uncertainty"
    only = forecast(points=(weather(),))
    corrected = engine.forecast((only,), T, (Observation(T, "i", 300),), Learner())
    assert corrected.model_status["i"] == "residual_no_uncertainty"
    reference, _ = module._instantaneous_reference(config(), {"a": only}, ("a",), Observation(T, "i", 300), T, (), Learner(), None, {})
    unchanged = engine.forecast((only,), T, (Observation(T, "i", reference.power_w),), Learner())
    assert unchanged.points[0].lower_w is not None
    assert unchanged.model_status["i"] == "residual_empirical_calibration"


@pytest.mark.parametrize("problem", ["missing", "weak", "numerical"])
def test_partial_ghi_reference_keeps_entire_two_model_cell_in_nwp_regime(monkeypatch, problem):
    issued, observed = START + timedelta(minutes=2), START - timedelta(minutes=1)
    previous = weather(START - timedelta(hours=1))
    future = (weather(), weather(START + timedelta(hours=1)))
    a = forecast(points=(previous, *future), issue=issued)
    b_reference = replace(previous, ghi_w_m2=30) if problem == "weak" else replace(previous, start=START - timedelta(minutes=30))
    b = forecast("b", future if problem == "missing" else (b_reference, *future), issued)
    engine = ForecastEngine(config())
    expected = engine.forecast((a, b), issued)
    if problem == "numerical":
        original = module.clear_sky_ghi_mean
        def mean(config, start, end):
            if start == b_reference.start:
                raise PhysicsUnavailable("nonfinite_clear_sky_ghi")
            return original(config, start, end)
        monkeypatch.setattr(module, "clear_sky_ghi_mean", mean)
    result = engine.forecast((a, b), issued, (Observation(observed, "i", ghi_w_m2=1000),))
    assert result.points == expected.points  # Neither dilute nor drop good NWP.
    for point in result.points:
        assert point.features["ghi_regime"] == point.features["ghi_observation_age_seconds"] == 0
        assert point.features["ghi_nowcast_gain"] == 1
        assert "ghi_observation_w_m2" not in point.features
    assert "ignored:incomplete_reference_cohort" in result.model_status.values()


def test_nwp_cell_fallback_also_uses_fully_nwp_instant_reference():
    issued, observed = START + timedelta(minutes=2), START - timedelta(minutes=1)
    previous = weather(START - timedelta(hours=1))
    future = (weather(), weather(START + timedelta(hours=1)))
    arms = (forecast(points=(previous, *future), issue=issued),
            forecast("b", (replace(previous, ghi_w_m2=30), *future), issued))
    engine = ForecastEngine(config())
    ghi = Observation(observed, "i", ghi_w_m2=1000)
    expected = engine.forecast(arms, issued, (ghi,))
    reference, _ = module._instantaneous_reference(config(), {a.model: a for a in arms}, ("a", "b"),
        Observation(observed, "i", 500), issued, (), None, None, {})
    result = engine.forecast(arms, issued, (ghi, Observation(observed, "i", reference.power_w)))
    assert result.points == expected.points
    assert result.model_status["power_nowcast:i"].startswith("usable:")


@pytest.mark.parametrize("missing_gain", [False, True])
def test_numerical_member_gap_preserves_cohort_and_regime_in_instant_cache(monkeypatch, missing_gain):
    first = forecast(points=tuple(weather(START + timedelta(hours=h)) for h in range(3)))
    second = forecast("b", tuple(replace(point, cloud_cover_pct=37,
        ghi_w_m2=30 if missing_gain and index == 0 else point.ghi_w_m2) for index, point in enumerate(first.points)))
    calculate, instant = module.inverter_power, module._instantaneous_reference
    seen = []
    def power(config, point, **kwargs):
        if point.cloud_cover_pct == 37:
            raise PhysicsUnavailable("nonfinite_string_dc_power")
        return calculate(config, point, **kwargs)
    def reference(*args):
        value = instant(*args)
        seen.append((args[2], value[0].features["ghi_regime"]))
        return value
    monkeypatch.setattr(module, "inverter_power", power)
    monkeypatch.setattr(module, "_instantaneous_reference", reference)
    observations = (Observation(T, "i", ghi_w_m2=1000), Observation(T, "i", power_w=500))
    engine = ForecastEngine(config())
    result = engine.forecast((first, second), T, observations)
    assert any(key.startswith("physics:b:") for key in result.model_status)
    assert all(models == ("a",) for models, _ in seen)
    assert {regime for _, regime in seen} == {0.0, 1.0}
    expected = engine.forecast((first,), T, observations)
    assert result.points == expected.points
