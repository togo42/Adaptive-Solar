"""Original timestamps and comparable normalized cohorts for optional smoothing."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from custom_components.adaptive_solar.core import engine
from custom_components.adaptive_solar.core.models import InverterConfig, Observation, SiteConfig, StringConfig, WeatherForecast
from custom_components.adaptive_solar.core.nowcast import PowerObservationHistory

T = datetime(2026, 6, 21, 11, tzinfo=timezone.utc)


def config(minutes=15):
    return SiteConfig(52, 13, "Europe/Berlin", (StringConfig("s", "i", 5, 30, 180),), (InverterConfig("i", 5),), power_nowcast_window_minutes=minutes)


def ref(baseline, *, ghi=False):
    return engine.InstantReference(baseline, baseline, {"ghi_regime": float(ghi), "beam_shade_factor": 1.0}, "physics")


def test_history_keeps_original_reports_deduplicates_and_expires():
    history = PowerObservationHistory(15, max_reports=3)
    old = Observation(T - timedelta(minutes=10), "i", power_w=500)
    latest = Observation(T, "i", power_w=1000)
    assert history.update((old,), T - timedelta(minutes=10), {"i": "clear"}) == (old,)
    rows = history.update((latest,), T, {"i": "clear"})
    assert rows == (latest, old)
    assert history.update((latest,), T, {"i": "clear"}) == rows
    next_obs = Observation(T + timedelta(minutes=6), "i", power_w=1100)
    assert history.update((next_obs,), T + timedelta(minutes=6), {"i": "clear"}) == (next_obs, latest)


def test_history_clears_on_missing_power_invalidity_or_recovered_phase():
    for changed in ((), (Observation(T, "i", curtailed=True),)):
        history = PowerObservationHistory(15)
        old = Observation(T - timedelta(minutes=10), "i", power_w=500)
        history.update((old,), old.time, {"i": ("clear", 1)})
        history.update(changed, T, {"i": ("clear", 1)})
        latest = Observation(T + timedelta(minutes=1), "i", power_w=1000)
        assert history.update((latest,), latest.time, {"i": ("clear", 1)}) == (latest,)
    history = PowerObservationHistory(15)
    history.update((old,), old.time, {"i": ("clear", 1)})
    # A monitored off/on excursion changes its recovery identity, even when
    # both refreshes see clear operation.
    assert history.update((latest,), latest.time, {"i": ("clear", 2)}) == (latest,)


def test_normalized_history_cancels_solar_trend_and_suppresses_latest_spike(monkeypatch):
    observations = [Observation(T - timedelta(minutes=10-index*5), "i", power_w=value)
                    for index, value in enumerate((550, 1100, 1650))]
    baselines = {obs.time: value for obs, value in zip(observations, (500, 1000, 1500), strict=True)}
    seen = []
    def reference(config, latest, models, obs, issued_at, fresh, *args):
        assert models == ("a",)
        assert all(item.time <= obs.time for item in fresh)
        seen.append(obs.time)
        return ref(baselines[obs.time]), "usable"
    monkeypatch.setattr(engine, "_instantaneous_reference", reference)
    latest = {"a": WeatherForecast("a", T - timedelta(hours=1), ())}
    def smooth(rows):
        return engine._smoothed_power_residual(config(), latest, ("a",), rows, rows[-1], T, rows,
                                               None, False, None, ref(1500))
    assert smooth(observations) == pytest.approx(150)
    spike = [*observations[:-1], replace(observations[-1], power_w=2025)]
    assert 150 < smooth(spike) < 525
    assert seen == [observations[0].time, observations[1].time] * 2


def test_unpaired_ghi_future_weather_or_missing_member_never_fill_history(monkeypatch):
    rows = [Observation(T - timedelta(minutes=5), "i", power_w=500), Observation(T, "i", power_w=1000)]
    weather = {"a": WeatherForecast("a", T - timedelta(hours=1), ())}
    # A GHI value newer than the older power report cannot explain that report.
    fresh = [*rows, Observation(T, "i", ghi_w_m2=500)]
    assert engine._smoothed_power_residual(config(), weather, ("a",), rows, rows[-1], T, fresh,
                                          None, True, None, ref(1000, ghi=True)) is None
    # Current source issued after the old measurement is not silently replayed
    # as the old measurement's prospective weather reference.
    weather["a"] = WeatherForecast("a", T - timedelta(minutes=1), ())
    assert engine._smoothed_power_residual(config(), weather, ("a",), rows, rows[-1], T, rows,
                                          None, False, None, ref(1000)) is None
    monkeypatch.setattr(engine, "_instantaneous_reference", lambda *args: (None, "ignored:no_original_weather_support"))
    weather["a"] = WeatherForecast("a", T - timedelta(hours=1), ())
    assert engine._smoothed_power_residual(config(), weather, ("a",), rows, rows[-1], T, rows,
                                          None, False, None, ref(1000)) is None


def test_single_report_candidate_preserves_default_public_nowcast():
    from custom_components.adaptive_solar.core.models import WeatherPoint
    weather = WeatherForecast("best_match", T - timedelta(hours=1), (
        WeatherPoint(T - timedelta(hours=1), T, 700, 650, 120, 20, 2, 10),
        WeatherPoint(T, T + timedelta(hours=1), 700, 650, 120, 20, 2, 10),
    ))
    report = Observation(T - timedelta(minutes=1), "i", power_w=2000)
    old = engine.ForecastEngine(config(0)).forecast((weather,), T, (report,))
    candidate = engine.ForecastEngine(config(15)).forecast((weather,), T, (report,))
    assert candidate.points == old.points
    assert candidate.model_status == old.model_status
