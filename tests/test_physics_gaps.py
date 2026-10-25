"""Numerical model gaps stay local; unexpected calculation errors propagate."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import math
from unittest.mock import Mock

import pytest

from custom_components.adaptive_solar.core import engine as engine_module, physics
from custom_components.adaptive_solar.core.engine import ForecastEngine
from custom_components.adaptive_solar.core.models import InverterConfig, Observation, SiteConfig, StringConfig, WeatherForecast, WeatherPoint

START = datetime(2026, 6, 21, 10, tzinfo=UTC)


def site(models=("a",)):
    return SiteConfig(52, 13, "Europe/Berlin", (StringConfig("s", "i", 5, 30, 180),),
                      (InverterConfig("i", 5),), weather_models=models)


def sources(model="a", ghi=700):
    return WeatherForecast(model, START, tuple(WeatherPoint(START + timedelta(hours=index),
        START + timedelta(hours=index + 1), ghi, ghi, 100, 20, 2, 20) for index in range(3)))


def two_stage_site(models=("a",)):
    config = site(models)
    return replace(config, strings=(*config.strings, StringConfig("peer_s", "peer", 3, 30, 90)),
        inverters=(*config.inverters, InverterConfig("peer", output_type="dc", max_output_kw=4)))


def corrupt_one_poa_cell(monkeypatch, ghi=700):
    original = physics.pvlib.irradiance.get_total_irradiance

    def transposition(**kwargs):
        poa = original(**kwargs)
        # Isolate the middle cell with its real solar geometry, not the engine
        # output. Every neighboring calculation still runs actual pvlib.
        middle = sources().points[1]
        sun = physics.solar_position(site(), middle.start + (middle.end - middle.start) / 2)
        if kwargs["ghi"] == ghi and kwargs["solar_zenith"] == sun.zenith_deg:
            poa["poa_diffuse"] = math.nan
        return poa

    monkeypatch.setattr(physics.pvlib.irradiance, "get_total_irradiance", transposition)


def test_nonfinite_poa_removes_only_affected_cell_and_keeps_valid_neighbors(monkeypatch):
    config, weather = site(), sources()
    expected = ForecastEngine(config).forecast((weather,), START)
    corrupt_one_poa_cell(monkeypatch)
    result = ForecastEngine(config).forecast((weather,), START)
    assert result.points == (expected.points[0], expected.points[2])
    assert all(point.power_w > 0 for point in result.points)
    assert result.power_at(START + timedelta(hours=1, minutes=30), "i") is None
    assert result.energy_kwh(START, START + timedelta(hours=3), "i") is None
    assert result.energy_kwh(START, START + timedelta(hours=1), "i") is not None
    key = f"physics:a:i:{weather.points[1].start.isoformat()}/{weather.points[1].end.isoformat()}"
    assert result.model_status[key] == "unavailable:nonfinite_poa_diffuse"


def test_valid_ensemble_member_is_not_averaged_with_zero_and_invalid_cohort_is_diagnosed(monkeypatch):
    config = site(("a", "b"))
    a, b = sources(), sources("b", ghi=400)
    engine = ForecastEngine(config)
    expected = engine.forecast((b,), START).points[1]
    corrupt_one_poa_cell(monkeypatch)
    result = engine.forecast((a, b), START)
    assert result.points[1] == expected
    assert result.energy_kwh(START, START + timedelta(hours=3), "i") is not None
    assert sum(key.startswith("physics:a:") for key in result.model_status) == 1
    assert not any(key.startswith("physics:b:") for key in result.model_status)


async def test_native_energy_omits_the_real_physics_gap_without_losing_neighbor_hours(hass, monkeypatch):
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.adaptive_solar.const import DOMAIN
    from custom_components.adaptive_solar.energy import async_get_solar_forecast

    config = site()
    corrupt_one_poa_cell(monkeypatch)
    source = sources()
    middle = source.points[1]
    # The missing half hour leaves two valid quarter hours in that SAME hour;
    # native Energy must not silently sum them into a purported full-hour Wh.
    segmented = replace(source, points=(source.points[0], replace(middle, end=middle.start + timedelta(minutes=15)),
        replace(middle, start=middle.start + timedelta(minutes=15), end=middle.start + timedelta(minutes=45)),
        replace(middle, start=middle.start + timedelta(minutes=45)), source.points[2]))
    result = ForecastEngine(config).forecast((segmented,), START)
    entry = MockConfigEntry(domain=DOMAIN, data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    entry.runtime_data = Mock(site=config, data=result, last_update_success=True)
    native = (await async_get_solar_forecast(hass, entry.entry_id))["wh_hours"]
    assert set(native) == {START.isoformat(), (START + timedelta(hours=2)).isoformat()}
    assert len(result.points) == 4
    assert result.energy_kwh(middle.start, middle.end, "i") is None
    for point in (result.points[0], result.points[-1]):
        assert native[point.start.isoformat()] == pytest.approx(point.power_w)


@pytest.mark.parametrize("target,quantity", [("extra", "extra_radiation"), ("direct", "poa_direct"),
    ("diffuse", "poa_diffuse"), ("temperature", "module_temperature"), ("dc", "string_dc_power")])
@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_nonfinite_pvlib_values_are_rejected_before_clipping(monkeypatch, target, quantity, value):
    if target == "extra":
        monkeypatch.setattr(physics.pvlib.irradiance, "get_extra_radiation", lambda *args: value)
    elif target in {"direct", "diffuse"}:
        monkeypatch.setattr(physics.pvlib.irradiance, "get_total_irradiance",
                            lambda **kwargs: {"poa_direct": value if target == "direct" else 500,
                                              "poa_diffuse": value if target == "diffuse" else 100})
    elif target == "temperature":
        monkeypatch.setattr(physics.pvlib.temperature, "faiman", lambda *args: value)
    else:
        monkeypatch.setattr(physics.pvlib.pvsystem, "pvwatts_dc", lambda *args: value)
    with pytest.raises(physics.PhysicsUnavailable, match=f"nonfinite_{quantity}"):
        physics.inverter_power(site(), sources().points[0])


@pytest.mark.parametrize("value", [math.nan, math.inf])
def test_nonfinite_string_sum_cannot_be_hidden_as_output_cap(monkeypatch, value):
    monkeypatch.setattr(physics, "string_dc_power", lambda *args, **kwargs: value)
    with pytest.raises(physics.PhysicsUnavailable, match="nonfinite_string_dc_sum"):
        physics.inverter_power(site(), sources().points[0])


def test_all_numerically_invalid_cells_remain_missing_instead_of_becoming_zeros(monkeypatch):
    monkeypatch.setattr(physics.pvlib.pvsystem, "pvwatts_dc", lambda *args: math.nan)
    result = ForecastEngine(site()).forecast((sources(),), START)
    assert result.points == ()
    assert result.power_at(START, "i") is None
    assert result.energy_kwh(START, START + timedelta(hours=3), "i") is None
    assert sum(key.startswith("physics:a:") for key in result.model_status) == 3


def test_nonfinite_solar_position_only_removes_its_supported_cell(monkeypatch):
    original = physics.pvlib.solarposition.get_solarposition
    bad_at = START + timedelta(hours=1, minutes=30)
    monkeypatch.setattr(physics, "_position", physics._position.__wrapped__)

    def geometry(times, *args):
        result = original(times, *args)
        if times[0] == bad_at:
            result.loc[:, "apparent_elevation"] = math.nan
        return result

    monkeypatch.setattr(physics.pvlib.solarposition, "get_solarposition", geometry)
    result = ForecastEngine(site()).forecast((sources(),), START)
    assert [point.start for point in result.points] == [START, START + timedelta(hours=2)]
    assert any(value == "unavailable:nonfinite_solar_position" for value in result.model_status.values())


def test_nonfinite_instant_reference_only_disables_optional_power_nowcast(monkeypatch):
    engine = ForecastEngine(site())
    expected = engine.forecast((sources(),), START)
    original = engine_module.inverter_power

    def calculate(*args, at=None, **kwargs):
        if at is not None:
            raise physics.PhysicsUnavailable("nonfinite_string_dc_power")
        return original(*args, **kwargs)

    monkeypatch.setattr(engine_module, "inverter_power", calculate)
    result = engine.forecast((sources(),), START, (Observation(START, "i", power_w=500),))
    assert result.points == expected.points
    assert result.model_status["power_nowcast:i"] == "ignored:nonfinite_physics"


@pytest.mark.parametrize("error", [ValueError, TypeError, RuntimeError, ZeroDivisionError])
def test_unexpected_pvlib_or_code_errors_are_not_reclassified_as_missing_data(monkeypatch, error):
    def broken(**kwargs):
        raise error("unexpected implementation error")

    monkeypatch.setattr(physics.pvlib.irradiance, "get_total_irradiance", broken)
    with pytest.raises(error, match="unexpected implementation error"):
        ForecastEngine(site()).forecast((sources(),), START)


def test_unexpected_optional_shape_error_also_propagates(monkeypatch):
    def broken(*args):
        raise ValueError("unexpected shape implementation error")

    monkeypatch.setattr(physics, "_clear_components", broken)
    with pytest.raises(ValueError, match="unexpected shape implementation error"):
        ForecastEngine(site()).forecast((sources(),), START, (Observation(START, "i", power_w=500),))


@pytest.mark.parametrize("latitude,time", [(52, datetime(2026, 6, 21, 2, 30, tzinfo=UTC)),
    (89.9, datetime(2026, 3, 20, 11, tzinfo=UTC)), (-89.9, datetime(2026, 9, 22, 11, tzinfo=UTC)),
    (0, datetime(2026, 3, 20, 11, tzinfo=UTC))])
def test_real_pvlib_low_sun_polar_and_near_zenith_inputs_remain_finite(latitude, time):
    config = replace(site(), latitude=latitude)
    weather = replace(sources().points[0], start=time, end=time + timedelta(hours=1))
    result = physics.inverter_power(config, weather)["i"]
    assert math.isfinite(result) and 0 <= result <= config.inverters[0].output_cap_w


def test_selected_stage_never_evaluates_an_unrelated_broken_string(monkeypatch):
    config, weather = two_stage_site(), sources().points[0]
    expected = physics.inverter_power(config, weather)
    original = physics.string_dc_power
    def power(config, string, point, **kwargs):
        if string.inverter_id == "i":
            raise physics.PhysicsUnavailable("nonfinite_string_dc_power")
        return original(config, string, point, **kwargs)
    monkeypatch.setattr(physics, "string_dc_power", power)
    assert physics.inverter_power(config, weather, inverter_id="peer") == {"peer": expected["peer"]}
    with pytest.raises(physics.PhysicsUnavailable):
        physics.inverter_power(config, weather)  # Historical all-stage call remains strict.
    with pytest.raises(ValueError, match="unknown output stage"):
        physics.inverter_power(config, weather, inverter_id="missing")


def test_one_stage_gap_keeps_same_model_cell_and_energy_of_healthy_peer(monkeypatch):
    config = two_stage_site()
    expected = ForecastEngine(config).forecast((sources(),), START)
    original = physics.string_dc_power
    def power(config, string, point, **kwargs):
        if string.inverter_id == "i" and point.start == START + timedelta(hours=1):
            raise physics.PhysicsUnavailable("nonfinite_string_dc_power")
        return original(config, string, point, **kwargs)
    monkeypatch.setattr(physics, "string_dc_power", power)
    result = ForecastEngine(config).forecast((sources(),), START)
    assert [point for point in result.points if point.inverter_id == "peer"] == [
        point for point in expected.points if point.inverter_id == "peer"]
    assert len(result.points) == 5
    assert result.energy_kwh(START, START + timedelta(hours=3), "peer") is not None
    assert result.energy_kwh(START, START + timedelta(hours=3)) is None
    assert all(key.startswith("physics:a:i:") for key in result.model_status if key.startswith("physics:"))


def test_stage_specific_survivors_choose_atomic_ghi_and_own_instant_reference(monkeypatch):
    config = two_stage_site(("a", "b"))
    issued, observed = START + timedelta(minutes=2), START - timedelta(minutes=1)
    previous = replace(sources().points[0], start=START - timedelta(hours=1), end=START)
    a = replace(sources(), issued_at=issued, points=(previous, *sources().points))
    b = replace(a, model="b", points=tuple(replace(point, cloud_cover_pct=37,
        ghi_w_m2=30 if index == 0 else 400) for index, point in enumerate(a.points)))
    calculate, instant = physics.string_dc_power, engine_module._instantaneous_reference
    seen = []
    def power(config, string, point, **kwargs):
        if string.inverter_id == "i" and point.cloud_cover_pct == 37:
            raise physics.PhysicsUnavailable("nonfinite_string_dc_power")
        return calculate(config, string, point, **kwargs)
    def reference(*args):
        result = instant(*args)
        seen.append((args[3].inverter_id, args[2], result[0].features["ghi_regime"]))
        return result
    monkeypatch.setattr(physics, "string_dc_power", power)
    monkeypatch.setattr(engine_module, "_instantaneous_reference", reference)
    ghi = Observation(observed, "i", ghi_w_m2=1000)
    meters = (Observation(observed, "i", power_w=500), Observation(observed, "peer", power_w=300))
    result = ForecastEngine(config).forecast((a, b), issued, (ghi, *meters))
    assert ("i", ("a",), 1.0) in seen and ("peer", ("a", "b"), 0.0) in seen
    for stage in config.inverters:
        own = replace(config, inverters=(stage,), strings=tuple(s for s in config.strings if s.inverter_id == stage.id))
        expected = ForecastEngine(own).forecast((a,) if stage.id == "i" else (a, b), issued,
            (replace(ghi, inverter_id=stage.id), next(m for m in meters if m.inverter_id == stage.id)))
        assert [point for point in result.points if point.inverter_id == stage.id] == list(expected.points)
    assert not any(key.startswith("physics:b:peer:") for key in result.model_status)
