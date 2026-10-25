"""Contract boundaries and interval coverage, including civil DST days."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from zoneinfo import ZoneInfo
import pytest
from custom_components.adaptive_solar.core.models import (
    MAX_FORECAST_DAYS, ForecastPoint, ForecastResult, HorizonPoint, InverterConfig, Observation,
    SiteConfig, StringConfig, TrainingSample, WeatherForecast, WeatherPoint,
)

UTC = timezone.utc
T = datetime(2026, 6, 21, 10, tzinfo=UTC)


def site():
    return SiteConfig(52, 13, "Europe/Berlin", (StringConfig("east", "shared", 5, 30, 90),), (InverterConfig("shared", 4),))


def test_config_json_roundtrip_and_references():
    config = site()
    assert SiteConfig.from_dict(json.loads(json.dumps(config.to_dict()))) == config
    with pytest.raises(ValueError, match="inverter"):
        SiteConfig(52, 13, "UTC", (StringConfig("east", "missing", 5, 30, 90),), (InverterConfig("shared", 4),))


@pytest.mark.parametrize("days", [1, 7])
def test_site_forecast_horizon_accepts_same_seven_day_contract_offline_and_json(days):
    config = replace(site(), forecast_days=days)
    assert MAX_FORECAST_DAYS == 7
    assert SiteConfig.from_dict(json.loads(json.dumps(config.to_dict()))).forecast_days == days


@pytest.mark.parametrize("days", [0, 8, 16, True, 7.0])
def test_site_forecast_horizon_rejects_more_than_seven_days_offline_and_json(days):
    with pytest.raises(ValueError, match="forecast_days.*1 to 7"):
        replace(site(), forecast_days=days)
    data = site().to_dict()
    data["forecast_days"] = days
    with pytest.raises(ValueError, match="forecast_days.*1 to 7"):
        SiteConfig.from_dict(json.loads(json.dumps(data)))


@pytest.mark.parametrize("invalid", [True, float("nan"), float("inf"), "3", -1])
def test_invalid_peak_is_rejected(invalid):
    with pytest.raises(ValueError):
        StringConfig("s", "i", invalid, 30, 180)


def test_naive_time_and_nonboolean_curtailment_rejected():
    with pytest.raises(ValueError, match="timezone"):
        Observation(datetime(2026, 1, 1), "i", 100)
    with pytest.raises(ValueError, match="boolean"):
        Observation(T, "i", 100, curtailed=1)


def test_times_normalize_to_utc_and_features_defensively_copied():
    local = T.astimezone(ZoneInfo("Europe/Berlin"))
    features = {"x": 1.0}
    point = ForecastPoint(local, local + timedelta(hours=1), "i", 1000, 1000, features=features)
    features["x"] = 999
    assert point.start == T and point.start.tzinfo is UTC
    assert point.features["x"] == 1


def test_no_overlaps_and_no_invented_gap_energy():
    points = (ForecastPoint(T, T + timedelta(hours=1), "i", 1000, 1000),
              ForecastPoint(T + timedelta(hours=2), T + timedelta(hours=3), "i", 1000, 1000))
    result = ForecastResult(T, points)
    assert result.energy_kwh(T + timedelta(minutes=15), T + timedelta(minutes=45)) == pytest.approx(0.5)
    assert result.energy_kwh(T, T + timedelta(hours=3)) is None
    assert result.power_at(T + timedelta(hours=1)) is None
    assert result.energy_kwh(T, T + timedelta(hours=1), "missing") is None
    with pytest.raises(ValueError, match="overlap"):
        ForecastResult(T, (points[0], points[0]))


@pytest.mark.parametrize("day,expected", [(datetime(2026, 3, 29), 23), (datetime(2026, 10, 25), 25)])
def test_local_dst_day_uses_actual_elapsed_hours(day, expected):
    zone = ZoneInfo("Europe/Berlin")
    start = day.replace(tzinfo=zone)
    end = start + timedelta(days=1)
    point = ForecastPoint(start, end, "i", 1000, 1000)
    assert ForecastResult(T, (point,)).energy_kwh(start, end) == expected


def test_site_sum_requires_coverage_of_every_present_inverter():
    result = ForecastResult(T, (ForecastPoint(T, T + timedelta(hours=2), "a", 1000, 1000),
        ForecastPoint(T, T + timedelta(hours=1), "b", 500, 500)))
    assert result.power_at(T) == 1500
    assert result.energy_kwh(T, T + timedelta(hours=1)) == 1.5
    assert result.energy_kwh(T, T + timedelta(hours=2)) is None
    assert result.power_at(T + timedelta(hours=1)) is None


def test_duplicate_circular_horizon_and_bad_bounds_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        StringConfig("s", "i", 1, 30, 180, horizon=(HorizonPoint(0, 10), HorizonPoint(360, 20)))
    with pytest.raises(ValueError, match="bracket"):
        ForecastPoint(T, T + timedelta(hours=1), "i", 100, 100, 200, 300)
    with pytest.raises(ValueError):
        TrainingSample(T, T, T + timedelta(hours=1), T, "i", 1, 2, {"x": float("nan")})


def test_weather_validation_and_sorting():
    def weather(start):
        return WeatherPoint(start, start + timedelta(hours=1), 500, 600, 100, 20, 2, 10)
    points = (weather(T + timedelta(hours=1)), weather(T))
    assert WeatherForecast("best_match", T, points).points[0].start == T
    with pytest.raises(ValueError, match="overlap"):
        WeatherForecast("best_match", T, (points[0], points[0]))
    with pytest.raises(ValueError):
        WeatherPoint(T, T + timedelta(hours=1), -1, 600, 100, 20, 2, 10)
