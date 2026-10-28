"""Behavioral checks for explicitly selected physical candidate options."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from custom_components.adaptive_solar.core import physics
from custom_components.adaptive_solar.core.engine import ForecastEngine
from custom_components.adaptive_solar.core.models import InverterConfig, SiteConfig, StringConfig, WeatherForecast, WeatherPoint
from custom_components.adaptive_solar.core.shading import BeamShadeTable, SHADE_MAX_AGE

T = datetime(2026, 6, 21, 11, tzinfo=timezone.utc)


def site(**kwargs):
    return SiteConfig(52, 13, "Europe/Berlin", (StringConfig("s", "i", 5, 30, 180),), (InverterConfig("i", 10),), **kwargs)


def weather(at=T):
    return WeatherPoint(at, at + timedelta(hours=1), 700, 600, 150, 20, 2, 10)


def test_neutral_candidates_keep_legacy_serialization_and_exact_power():
    config = site()
    encoded = config.to_dict()
    assert "physics_substeps" not in encoded
    assert "power_nowcast_window_minutes" not in encoded
    for key in ("iam_ashrae_b0", "faiman_u0", "faiman_u1", "wind_speed_factor"):
        assert key not in encoded["strings"][0]
    assert SiteConfig.from_dict(encoded) == config
    assert physics.interval_inverter_power(config, weather()) == physics.inverter_power(config, weather())
    assert physics.interval_inverter_power(config, weather(), start=T + timedelta(minutes=10)) == physics.inverter_power(config, replace(weather(), start=T + timedelta(minutes=10)))


@pytest.mark.parametrize("name,value", [("iam_ashrae_b0", .21), ("faiman_u0", 0), ("faiman_u1", -1), ("wind_speed_factor", 3)])
def test_physics_parameters_have_validated_numerical_bounds(name, value):
    with pytest.raises(ValueError):
        replace(site().strings[0], **{name: value})


def test_iam_reduces_grazing_direct_beam_without_changing_diffuse(monkeypatch):
    cfg = site()
    string = replace(cfg.strings[0], iam_ashrae_b0=.05)
    monkeypatch.setattr(physics, "solar_position", lambda *_: physics.SolarPosition(20, 180, 70))
    normal = replace(string, tilt_deg=70)
    grazing = replace(string, tilt_deg=0)
    w = weather()
    for candidate in (normal, grazing):
        assert physics.string_dc_power(cfg, candidate, replace(w, dni_w_m2=0)) == physics.string_dc_power(cfg, replace(candidate, iam_ashrae_b0=0), replace(w, dni_w_m2=0))
    def ratio(candidate):
        return physics.string_dc_power(cfg, candidate, w) / physics.string_dc_power(cfg, replace(candidate, iam_ashrae_b0=0), w)
    assert ratio(normal) == pytest.approx(1)
    assert ratio(grazing) < .98


def test_faiman_and_wind_reference_parameters_change_temperature_losses():
    cfg = site()
    original = physics.inverter_power(cfg, weather())["i"]
    for params in ({"faiman_u0": 40}, {"faiman_u1": 12}, {"wind_speed_factor": 1.5}):
        changed = replace(cfg, strings=(replace(cfg.strings[0], **params),))
        assert physics.inverter_power(changed, weather())["i"] > original


def test_subinterval_shared_clipping_precedes_energy_average_and_keeps_original_support(monkeypatch):
    cfg = site(physics_substeps=4)
    source = weather()
    supports = []
    monkeypatch.setattr(physics, "solar_position", lambda *_: physics.SolarPosition(30, 180, 60))
    def proxy(config, original, at, **kwargs):
        supports.append((original.start, original.end, original.ghi_w_m2))
        # Deliberately cross a shared cap within the output interval.
        return replace(original, ghi_w_m2=400 if at.minute < 30 else 1200)
    monkeypatch.setattr(physics, "instantaneous_weather", proxy)
    monkeypatch.setattr(physics, "inverter_power", lambda config, point, **kwargs: {"i": min(800, point.ghi_w_m2)})
    assert physics.interval_inverter_power(cfg, source)["i"] == 600
    assert physics.interval_inverter_power(cfg, source, start=T + timedelta(minutes=30))["i"] == 800
    assert set(supports) == {(source.start, source.end, 700)}
    assert source == weather()


@pytest.mark.parametrize("at", [datetime(2026, 3, 29, 0, tzinfo=timezone.utc), datetime(2026, 10, 25, 0, tzinfo=timezone.utc)])
def test_subintervals_use_real_utc_duration_across_both_dst_changes(at, monkeypatch):
    cfg = site(physics_substeps=4)
    seen = []
    monkeypatch.setattr(physics, "solar_position", lambda *_: physics.SolarPosition(30, 180, 60))
    monkeypatch.setattr(physics, "instantaneous_weather", lambda config, original, instant, **kwargs: original)
    def power(config, point, *, at, **kwargs):
        seen.append(at)
        return {"i": 1000}
    monkeypatch.setattr(physics, "inverter_power", power)
    assert physics.interval_inverter_power(cfg, weather(at))["i"] == 1000
    assert seen == [at + timedelta(minutes=7.5 + index * 15) for index in range(4)]


def test_member_archive_retains_real_models_issues_and_original_nwp_without_local_adjustment():
    cfg = site(weather_models=("a", "b"))
    forecasts = (WeatherForecast("a", T, (weather(),)), WeatherForecast("b", T - timedelta(hours=1), (replace(weather(), ghi_w_m2=500),)))
    from custom_components.adaptive_solar.core.models import Observation
    result = ForecastEngine(cfg).forecast(forecasts, T, (Observation(T, "i", temperature_c=50),))
    assert set(result.member_points) == {"a", "b"}
    assert result.member_issued_at == {"a": T, "b": T - timedelta(hours=1)}
    assert result.member_points["a"][0].features["temperature_c"] == 20
    assert result.member_points["a"][0].power_w == physics.inverter_power(cfg, weather())["i"]
    assert result.points[0].features["temperature_c"] > 20


def seeded_shade(factor=.2):
    table = BeamShadeTable()
    for offset in range(6):
        at = T - timedelta(days=2 - offset // 2, minutes=(offset % 2) * 15)
        assert table.record("i", 180, 40, at, factor, as_of=T)
    return table


def test_shade_requires_distinct_days_expires_and_rejects_future_measurements():
    table = BeamShadeTable()
    for offset in range(6):
        table.record("i", 180, 40, T - timedelta(minutes=offset * 15), .2, as_of=T)
    assert table.transmittance("i", 180, 40, as_of=T) == 1
    assert table.status_for("i", 180, 40, as_of=T)["release_reason"] == "insufficient_days"
    assert not table.record("i", 180, 40, T + timedelta(seconds=1), .2, as_of=T)
    table = seeded_shade()
    assert table.transmittance("i", 180, 40, as_of=T) == .2
    assert table.transmittance("i", 180, 40, as_of=T + SHADE_MAX_AGE + timedelta(days=1)) == 1
    assert table.transmittance("i", 180, 40, as_of=T - timedelta(days=10)) == 1


def test_shade_robust_daily_dispersion_and_persisted_bounded_drift():
    table = seeded_shade()
    # Repeated same-day polling cannot change the released baseline.
    for offset in range(6):
        table.record("i", 180, 40, T + timedelta(minutes=offset * 15), .4, as_of=T + timedelta(hours=2))
    assert table.transmittance("i", 180, 40, as_of=T + timedelta(hours=2)) == .2
    restored = BeamShadeTable.from_dict(table.to_dict(), inverter_ids={"i"})
    assert restored.to_dict() == table.to_dict()
    for offset in range(6):
        at = T + timedelta(days=1, minutes=offset * 15)
        restored.record("i", 180, 40, at, .4, as_of=at)
    assert restored.transmittance("i", 180, 40, as_of=T + timedelta(days=1, hours=2)) <= .3 + 1e-9
    unstable = BeamShadeTable()
    for day in range(2):
        for quarter in range(3):
            unstable.record("i", 180, 40, T - timedelta(days=day, minutes=quarter * 15), float(day), as_of=T)
    assert unstable.transmittance("i", 180, 40, as_of=T) == 1
    assert unstable.status_for("i", 180, 40, as_of=T)["release_reason"] == "unstable_daily_transmittance"


def test_candidate_resolves_daylight_crossing_with_original_clear_sky_hour_means():
    config = site(physics_substeps=12)
    start = T.replace(hour=2)
    end = start + timedelta(hours=1)
    means = physics._clear_component_means(config.latitude, config.longitude, start, end)
    source = WeatherPoint(start, end, *means, 15, 2, 10)
    assert physics.inverter_power(config, source)["i"] == 0
    assert physics.interval_inverter_power(config, source)["i"] > 0
    assert (source.ghi_w_m2, source.dni_w_m2, source.dhi_w_m2) == means


def test_shade_unchanged_release_does_not_expire_while_samples_stay_fresh():
    table = seeded_shade()
    for day in range(1, 45):
        at = T + timedelta(days=day)
        table.record("i", 180, 40, at, .2, as_of=at)
    cloudy_day = T + timedelta(days=46)
    assert table.status_for("i", 180, 40, as_of=cloudy_day)["released"]
    assert table.transmittance("i", 180, 40, as_of=cloudy_day) == .2
    assert table.transmittance("i", 180, 40, as_of=T + timedelta(days=90)) == 1


def test_shade_later_same_quarter_report_cannot_rewrite_earlier_as_of():
    table = BeamShadeTable()
    quarter = T.replace(minute=0)
    first = quarter + timedelta(minutes=1)
    before = quarter + timedelta(minutes=2)
    for day in range(1, 5):
        stamp = quarter - timedelta(days=day)
        table.record("i", 180, 40, stamp, .9, as_of=stamp)
    table.record("i", 180, 40, first, .9, as_of=first)
    original = table.status_for("i", 180, 40, as_of=before)
    assert original["released"]
    assert not table.record("i", 180, 40, quarter + timedelta(minutes=14), 0,
                            as_of=quarter + timedelta(minutes=14))
    assert table.status_for("i", 180, 40, as_of=before) == original
    restored = BeamShadeTable.from_dict(table.to_dict())
    assert restored.status_for("i", 180, 40, as_of=before) == original


def test_shade_receipt_and_release_history_do_not_backdate_evidence():
    table = BeamShadeTable()
    for day in range(5):
        table.record("i", 180, 40, T - timedelta(days=day), .2, as_of=T)
    assert table.transmittance("i", 180, 40, as_of=T - timedelta(seconds=1)) == 1
    original = table.transmittance("i", 180, 40, as_of=T)
    assert original == .2
    for day in range(1, 6):
        stamp = T + timedelta(days=day)
        table.record("i", 180, 40, stamp, .4, as_of=stamp)
    assert table.transmittance("i", 180, 40, as_of=T) == original
    assert table.transmittance("i", 180, 40, as_of=T + timedelta(days=5)) > original
    restored = BeamShadeTable.from_dict(table.to_dict())
    assert restored.transmittance("i", 180, 40, as_of=T) == original


@pytest.mark.parametrize("schema", [1, 2])
def test_legacy_shade_samples_remain_visible_but_cannot_invent_receipt_times(schema):
    legacy = {"schema": schema, "inverters": {"i": {"180:40": [
        {"quarter_hour": (T - timedelta(days=day)).isoformat(), "factor": .2}
        for day in range(5)]}}}
    table = BeamShadeTable.from_dict(legacy)
    status = table.status_for("i", 180, 40, as_of=T)
    assert status["unqualified_legacy_samples"] == 5
    assert not status["released"] and status["samples"] == 0
    assert table.transmittance("i", 180, 40, as_of=T) == 1
    encoded = table.to_dict()
    assert encoded["schema"] == 3
    assert encoded["unqualified_legacy"] == legacy["inverters"]
    assert BeamShadeTable.from_dict(encoded).to_dict() == encoded
