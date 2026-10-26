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


def test_beam_shade_factor_scales_direct_only_across_stage_strings_and_rejects_invalid():
    strings = (
        StringConfig("wall", "i", 3.0, 45, 160, horizon=(HorizonPoint(0, 90, 0.8),), damping_morning=0.1),
        StringConfig("shed", "i", 2.0, 15, 220, loss_fraction=0.12),
    )
    ac_cfg = config(strings, cap=4.0)
    dc_cfg = SiteConfig(52, 13, "Europe/Berlin", strings, (InverterConfig("i", output_type="dc", max_output_kw=4.0, dc_loss_fraction=0.05),))
    w = weather()
    # Factor 1 reproduces default string and stage power across AC and DC boundaries.
    for s in strings:
        assert string_dc_power(ac_cfg, s, w, beam_shade_factor=1.0) == string_dc_power(ac_cfg, s, w)
    assert inverter_power(ac_cfg, w, beam_shade_factor=1.0) == inverter_power(ac_cfg, w)
    assert inverter_power(dc_cfg, w, beam_shade_factor=1.0) == inverter_power(dc_cfg, w)
    # Factor 0 removes direct beam (matching a full horizon block) while preserving diffuse.
    for s in strings:
        blocked_horizon = replace(s, horizon=(HorizonPoint(0, 90, 0.0),))
        assert string_dc_power(ac_cfg, s, w, beam_shade_factor=0.0) == pytest.approx(
            string_dc_power(ac_cfg, blocked_horizon, w)
        )
    # Partial factor lies strictly between 0 and 1 and applies equally to both strings on the stage.
    unclipped_cfg = config(strings, cap=20.0)
    p0 = inverter_power(unclipped_cfg, w, beam_shade_factor=0.0)["i"]
    p_half = inverter_power(unclipped_cfg, w, beam_shade_factor=0.5)["i"]
    p1 = inverter_power(unclipped_cfg, w, beam_shade_factor=1.0)["i"]
    expected_half = sum(string_dc_power(unclipped_cfg, s, w, beam_shade_factor=0.5) for s in strings) * unclipped_cfg.inverters[0].efficiency
    assert 0 < p0 < p_half < p1
    assert p_half == pytest.approx(expected_half)
    # Diffuse-only weather is unaffected by beam_shade_factor.
    diffuse_only = replace(w, dni_w_m2=0)
    assert inverter_power(unclipped_cfg, diffuse_only, beam_shade_factor=0.0)["i"] == pytest.approx(
        inverter_power(unclipped_cfg, diffuse_only, beam_shade_factor=1.0)["i"]
    )
    # Non-finite or out-of-range factors are rejected even at night.
    for invalid in (float("nan"), float("inf"), -float("inf"), -0.01, 1.01, True):
        with pytest.raises(ValueError):
            string_dc_power(ac_cfg, strings[0], w, beam_shade_factor=invalid)
        with pytest.raises(ValueError):
            inverter_power(ac_cfg, weather(T.replace(hour=23)), beam_shade_factor=invalid)
