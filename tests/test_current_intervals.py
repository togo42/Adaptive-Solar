"""AS-001: remaining-cell means must carry remaining-cell time support."""
from datetime import datetime, timedelta, timezone
from math import exp
from unittest.mock import Mock

from freezegun import freeze_time
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_solar.core import engine as engine_module
from custom_components.adaptive_solar.core.engine import ForecastEngine, InstantReference, _irradiance_gains, _irradiance_weight
from custom_components.adaptive_solar.core.models import InverterConfig, Observation, SiteConfig, StringConfig, WeatherForecast, WeatherPoint
from custom_components.adaptive_solar.core.physics import solar_position
from custom_components.adaptive_solar.coordinator import AdaptiveSolarCoordinator, join_training
from custom_components.adaptive_solar.sensor import AdaptiveSolarSensor

UTC = timezone.utc
START = datetime(2026, 6, 21, 10, tzinfo=UTC)


def site():
    return SiteConfig(50, 10, "Europe/Berlin", (StringConfig("s", "i", 5, 30, 180),),
                      (InverterConfig("i", 5),), weather_models=("a",), forecast_days=1)


def weather(start=START, minutes=60):
    return WeatherPoint(start, start + timedelta(minutes=minutes), 500, 600, 150, 20, 2, 0)


def source(issued, points=None):
    return WeatherForecast("a", issued, tuple(points or (weather(), weather(START + timedelta(hours=1)))))


@pytest.mark.parametrize("minute", [0, 5, 50])
def test_output_starts_at_issue_and_uses_its_actual_target_midpoint(minute):
    issued = START + timedelta(minutes=minute)
    forecast = source(issued)
    original = forecast.points
    result = ForecastEngine(site()).forecast((forecast,), issued)
    point = result.points[0]
    assert point.start == issued
    assert point.end == START + timedelta(hours=1)
    assert point.features["source_partial_at_issue"] == (0.0 if minute == 0 else 1.0)
    midpoint = issued + (point.end - issued) / 2
    assert point.features["lead_hours"] == pytest.approx((midpoint - issued).total_seconds() / 3600)
    assert point.features["sun_elevation_deg"] == solar_position(site(), midpoint).elevation_deg
    assert forecast.points == original and forecast.points[0].start == START
    assert all(point.start >= issued for point in result.points)
    assert result.points[1].features["source_partial_at_issue"] == 0
    if minute:
        assert result.power_at(issued - timedelta(microseconds=1)) is None
        assert result.energy_kwh(START, point.end) is None
    assert result.energy_kwh(issued, point.end) == pytest.approx(point.power_w * (point.end - issued).total_seconds() / 3_600_000)


def test_issue_inside_missing_source_coverage_does_not_create_a_partial_point():
    issued = START + timedelta(minutes=50)
    forecast = source(issued, (weather(minutes=40), weather(START + timedelta(hours=1))))
    result = ForecastEngine(site()).forecast((forecast,), issued)
    assert result.points[0].start == START + timedelta(hours=1)
    assert result.points[0].features["source_partial_at_issue"] == 0
    assert result.power_at(issued) is None
    assert result.energy_kwh(issued, result.points[0].end) is None


def test_remaining_ghi_energy_equals_decay_integral_without_full_hour_inflation(monkeypatch):
    issued = START + timedelta(minutes=50)
    observed = Observation(issued, "i", ghi_w_m2=750)
    monkeypatch.setattr(engine_module, "_irradiance_gains", lambda *args: (observed, {"a": 1.5}, "usable:test"))
    monkeypatch.setattr(engine_module, "inverter_power", lambda config, point, **kwargs: {"i": point.ghi_w_m2 * 2})
    result = ForecastEngine(site()).forecast((source(issued),), issued, (observed,))
    point = result.points[0]
    duration_hours = (point.end - point.start).total_seconds() / 3600
    base_kwh = 1000 * duration_hours / 1000
    correction_kwh = 1000 * 0.5 * 0.5 * (1 - exp(-duration_hours / 0.5)) / 1000
    assert result.energy_kwh(issued, point.end) == pytest.approx(base_kwh + correction_kwh)
    assert point.power_w * duration_hours / 1000 == pytest.approx(base_kwh + correction_kwh)
    assert duration_hours == pytest.approx(1 / 6)
    assert point.features["ghi_regime"] == 1


def test_remaining_power_nowcast_energy_equals_decay_integral_without_full_hour_inflation(monkeypatch):
    issued = START + timedelta(minutes=50)
    forecast = source(issued)
    monkeypatch.setattr(engine_module, "inverter_power", lambda config, point, **kwargs: {"i": 1000.0})
    def instant(config, forecasts, *args):
        assert forecasts["a"].points[0].start == START  # Original evidence remains full source support.
        return InstantReference(1000, 1000, {"ghi_regime": 0}, "physics"), "usable:test"
    monkeypatch.setattr(engine_module, "_instantaneous_reference", instant)
    result = ForecastEngine(site()).forecast((forecast,), issued, (Observation(issued, "i", power_w=1200),))
    point = result.points[0]
    duration_hours = (point.end - point.start).total_seconds() / 3600
    expected_kwh = duration_hours + 0.5 * 200 * 0.75 * (1 - exp(-duration_hours / 0.75)) / 1000
    assert point.power_w * duration_hours / 1000 == pytest.approx(expected_kwh)
    assert result.energy_kwh(issued, point.end) == pytest.approx(expected_kwh)
    assert result.power_at(START) is None


def test_partial_target_does_not_change_original_ghi_normalization_interval():
    issued = START + timedelta(minutes=50)
    observed = Observation(issued, "i", ghi_w_m2=800)
    forecast = source(issued)
    _, gains, _ = _irradiance_gains(site(), {"a": forecast}, (observed,), issued)
    result = ForecastEngine(site()).forecast((forecast,), issued, (observed,))
    expected_gain = 1 + (gains["a"] - 1) * _irradiance_weight(issued, forecast.points[0].end, issued, observed.time)
    assert result.points[0].features["ghi_nowcast_gain"] == pytest.approx(expected_gain)
    assert forecast.points[0].start == START


@pytest.mark.parametrize("issued", [datetime(2026, 3, 29, 0, 50, tzinfo=UTC),
                                    datetime(2026, 10, 25, 0, 50, tzinfo=UTC),
                                    datetime(2026, 10, 25, 1, 50, tzinfo=UTC)])
def test_partial_duration_is_true_elapsed_time_across_both_dst_transitions(monkeypatch, issued):
    start = issued.replace(minute=0)
    forecast = source(issued, (weather(start),))
    # Isolate the time/energy contract; other tests cover actual night physics.
    monkeypatch.setattr(engine_module, "inverter_power", lambda config, point, **kwargs: {"i": 1000.0})
    result = ForecastEngine(site()).forecast((forecast,), issued)
    point = result.points[0]
    assert (point.end - point.start).total_seconds() == 600
    assert result.energy_kwh(issued, point.end) == pytest.approx(1 / 6)


async def test_quality_partial_wh_matches_result_and_training_cannot_relabel_full_hour(hass, monkeypatch):
    issued = START + timedelta(minutes=15)
    config = site()
    monkeypatch.setattr(engine_module, "inverter_power", lambda config, point, **kwargs: {"i": 1000.0})
    result = ForecastEngine(config).forecast((source(issued),), issued)
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    coordinator = Mock(site=config, data=result, last_update_success=True, learner_status={}, input_quality={},
                       client=Mock(errors={}), intervals=[], archive=[])
    quality = AdaptiveSolarSensor(coordinator, entry, "i", "quality")
    with freeze_time(issued):
        row = quality.extra_state_attributes["forecast"][0]
    assert datetime.fromisoformat(row["start"]) == issued
    assert row["energy_kwh"] == pytest.approx(0.75)
    assert row["energy_kwh"] == pytest.approx(result.energy_kwh(issued, START + timedelta(hours=1)))
    assert row["power_w"] * 45 / 60 / 1000 == row["energy_kwh"]
    point = result.points[0]
    archive = [{"issued_at": issued.isoformat(), "start": point.start.isoformat(), "end": point.end.isoformat(),
        "inverter_id": "i", "baseline_w": point.baseline_w, "features": dict(point.features)}]
    full_hour_actual = [{"start": START.isoformat(), "end": (START + timedelta(hours=1)).isoformat(),
        "observed_at": (START + timedelta(hours=1)).isoformat(), "inverter_id": "i", "energy_kwh": 1.0}]
    assert join_training(archive, full_hour_actual) == []  # Never split a meter delta to fabricate its boundary.
    # The coordinator additionally rejects these issue-created targets entirely,
    # avoiding a different short-lived target on every HA refresh.
    live = AdaptiveSolarCoordinator(hass, entry, config, Mock())
    live._archive_result(result)
    assert all(row["start"] != issued.isoformat() for row in live.archive)
    await live.async_close()
