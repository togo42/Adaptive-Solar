from dataclasses import replace
from datetime import datetime, timedelta, timezone
import pytest
from custom_components.adaptive_solar.core.models import HorizonPoint, InverterConfig, SiteConfig, StringConfig, WeatherPoint
from custom_components.adaptive_solar.core.physics import horizon_at, inverter_power, solar_position, string_dc_power

T = datetime(2026, 6, 21, 11, tzinfo=timezone.utc)


def config(strings=None, cap=20):
    return SiteConfig(52, 13, "Europe/Berlin", strings or (StringConfig("s", "i", 5, 30, 180),), (InverterConfig("i", cap),))


def weather(start=T, temperature=20, wind=2):
    return WeatherPoint(start, start + timedelta(hours=1), 850, 800, 150, temperature, wind, 10)


def test_circular_horizon_interpolates_both_elevation_and_transmission():
    horizon = (HorizonPoint(350, 10, 0), HorizonPoint(10, 30, 0.8))
    assert horizon_at(horizon, 0) == pytest.approx((20, 0.4))
    assert horizon_at(horizon, 360) == pytest.approx((20, 0.4))


def test_partial_beam_shadow_preserves_diffuse_and_interpolates_power():
    cfg = config()
    string = cfg.strings[0]
    clear = string_dc_power(cfg, string, weather())
    blocked = string_dc_power(cfg, replace(string, horizon=(HorizonPoint(0, 90, 0),)), weather())
    partial = string_dc_power(cfg, replace(string, horizon=(HorizonPoint(0, 90, 0.5),)), weather())
    # Faiman temperature changes under shading, so power need not be exactly linear.
    assert 0 < blocked < partial < clear
    diffuse = replace(weather(), dni_w_m2=0)
    assert string_dc_power(cfg, string, diffuse) == pytest.approx(string_dc_power(cfg, replace(string, horizon=(HorizonPoint(0, 90),)), diffuse))


def test_inverter_cap_applied_once_after_multiple_orientations():
    strings = (StringConfig("east", "i", 5, 30, 90), StringConfig("west", "i", 5, 30, 270))
    cfg = config(strings, cap=3)
    raw = sum(string_dc_power(cfg, s, weather()) for s in strings) * cfg.inverters[0].efficiency
    assert raw > 3000
    assert inverter_power(cfg, weather())["i"] == 3000


def test_night_forces_zero_even_if_weather_contains_nonzero_radiation():
    cfg = config()
    assert inverter_power(cfg, weather(T.replace(hour=23)))["i"] == 0


def test_fresh_weather_temperature_and_wind_affect_physical_power():
    cfg = config()
    assert inverter_power(cfg, weather(temperature=5))["i"] > inverter_power(cfg, weather(temperature=35))["i"]
    assert inverter_power(cfg, weather(wind=10))["i"] > inverter_power(cfg, weather(wind=0))["i"]


def test_solarposition_azimuth_convention():
    position = solar_position(config(), T)
    assert position.elevation_deg > 50
    assert 150 < position.azimuth_deg < 210
