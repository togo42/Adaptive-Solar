"""Explicit AC/DC output boundaries; every installation here is fictional."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from custom_components.adaptive_solar.core.engine import ForecastEngine, _instantaneous_reference
from custom_components.adaptive_solar.core.models import InverterConfig, Observation, SiteConfig, StringConfig, WeatherForecast, WeatherPoint
from custom_components.adaptive_solar.core.physics import inverter_power, string_dc_power

UTC = timezone.utc
START = datetime(2026, 6, 21, 11, tzinfo=UTC)


def site(stage=None, strings=None):
    stage = stage or InverterConfig("shared", 30)
    return SiteConfig(49, 9, "Europe/Berlin", strings or (
        StringConfig("fictional_east", stage.id, 2.4, 25, 90),
        StringConfig("fictional_west", stage.id, 3.3, 40, 270)), (stage,), weather_models=("a",))


def weather(start=START):
    return WeatherPoint(start, start + timedelta(hours=1), 900, 850, 160, 22, 2, 5)


def test_legacy_ac_positions_defaults_numbers_and_json_remain_exact():
    legacy = InverterConfig("shared", 4, 0.96, "sensor.p", "sensor.e", "binary_sensor.limit")
    expected = {"id": "shared", "max_ac_kw": 4.0, "efficiency": 0.96,
        "power_entity_id": "sensor.p", "energy_entity_id": "sensor.e", "curtailed_entity_id": "binary_sensor.limit"}
    assert legacy.to_dict() == expected
    assert InverterConfig("shared", 4).efficiency == 0.96
    assert legacy.output_type == "ac"
    assert legacy.max_output_kw == legacy.max_ac_kw == 4
    assert legacy.output_cap_w == 4000
    assert site(legacy).to_dict()["inverters"] == [expected]
    canonical = InverterConfig("shared", efficiency=0.96, power_entity_id="sensor.p", energy_entity_id="sensor.e",
        curtailed_entity_id="binary_sensor.limit", output_type="ac", max_output_kw=4)
    assert canonical == legacy
    assert canonical.to_dict() == expected
    assert SiteConfig.from_dict(json.loads(json.dumps(site(legacy).to_dict()))) == site(legacy)


def test_dc_json_has_only_its_declared_stage_and_no_ac_alias_or_efficiency():
    dc = InverterConfig("shared", output_type="dc", max_output_kw=5, dc_loss_fraction=0.02,
                        power_entity_id="sensor.p", energy_entity_id="sensor.e")
    assert dc.max_ac_kw is None and dc.efficiency is None
    assert dc.max_output_kw == 5 and dc.output_cap_w == 5000
    payload = site(dc).to_dict()
    serialized = payload["inverters"][0]
    assert serialized == {"id": "shared", "output_type": "dc", "max_output_kw": 5.0, "dc_loss_fraction": 0.02,
        "power_entity_id": "sensor.p", "energy_entity_id": "sensor.e", "curtailed_entity_id": None}
    assert "max_ac_kw" not in serialized and "efficiency" not in serialized
    assert SiteConfig.from_dict(json.loads(json.dumps(payload))) == site(dc)
    assert payload != site(InverterConfig("shared", 5)).to_dict()  # Stage changes invalidate the semantic config fingerprint.


@pytest.mark.parametrize("kwargs", [
    {"output_type": "dc", "max_ac_kw": 5},
    {"output_type": "dc", "max_ac_kw": 5, "max_output_kw": 5},
    {"output_type": "dc", "max_output_kw": 5, "efficiency": 0.96},
    {"output_type": "dc", "max_output_kw": 5, "efficiency": 1.0},
    {"output_type": "dc"},
    {"output_type": "ac", "max_ac_kw": 4, "max_output_kw": 5},
    {"output_type": "ac", "max_ac_kw": 4, "dc_loss_fraction": 0.01},
    {"output_type": "DC", "max_output_kw": 5},
    {"output_type": True, "max_output_kw": 5},
])
def test_ambiguous_stage_efficiency_or_limits_are_rejected(kwargs):
    with pytest.raises(ValueError):
        InverterConfig("shared", **kwargs)


@pytest.mark.parametrize("value", [True, -1, 0, float("nan"), float("inf"), "5"])
def test_dc_output_limit_requires_finite_positive_number(value):
    with pytest.raises(ValueError):
        InverterConfig("shared", output_type="dc", max_output_kw=value)


@pytest.mark.parametrize("value", [True, -0.01, 1.01, float("nan"), float("inf"), "0.1"])
def test_explicit_dc_stage_losses_are_validated(value):
    with pytest.raises(ValueError):
        InverterConfig("shared", output_type="dc", max_output_kw=5, dc_loss_fraction=value)


def test_dc_has_no_hidden_4_percent_ac_conversion_loss():
    ac = site(InverterConfig("shared", 30))
    dc = site(InverterConfig("shared", output_type="dc", max_output_kw=30))
    raw = sum(string_dc_power(dc, string, weather()) for string in dc.strings)
    assert 0 < raw < 30000
    assert inverter_power(dc, weather())["shared"] == raw
    assert inverter_power(ac, weather())["shared"] == raw * 0.96  # Historical exact operation/order.


def test_explicit_dc_losses_follow_string_sum_then_one_shared_dc_output_cap():
    stage = InverterConfig("shared", output_type="dc", max_output_kw=1.3, dc_loss_fraction=0.08)
    config = site(stage)
    raw = sum(string_dc_power(config, string, weather()) for string in config.strings)
    assert raw * (1 - stage.dc_loss_fraction) > stage.output_cap_w
    assert inverter_power(config, weather())["shared"] == 1300
    # Neither per-string clipping nor a clip followed by stage losses is valid.
    assert inverter_power(config, weather())["shared"] != 1300 * (1 - stage.dc_loss_fraction)
    uncapped = site(replace(stage, max_output_kw=30))
    assert inverter_power(uncapped, weather())["shared"] == raw * 0.92
    lost = site(replace(stage, dc_loss_fraction=1))
    assert inverter_power(lost, weather())["shared"] == 0


def test_instantaneous_dc_reference_and_mean_forecast_share_same_declared_boundary():
    stage = InverterConfig("shared", output_type="dc", max_output_kw=30)
    config = site(stage)
    issued = START + timedelta(minutes=5)
    forecast = WeatherForecast("a", issued, (weather(), weather(START + timedelta(hours=1))))
    observed = Observation(issued, "shared", power_w=500)
    reference, status = _instantaneous_reference(config, {"a": forecast}, ("a",), observed, issued, (observed,), None, None, {})
    ac = site(InverterConfig("shared", 30))
    ac_reference, _ = _instantaneous_reference(ac, {"a": forecast}, ("a",), observed, issued, (observed,), None, None, {})
    assert status.startswith("usable")
    assert ac_reference.power_w == reference.power_w * 0.96
    result = ForecastEngine(config).forecast((forecast,), issued)
    ac_result = ForecastEngine(ac).forecast((forecast,), issued)
    assert [point.power_w for point in ac_result.points] == [point.power_w * 0.96 for point in result.points]
    first = result.points[0]
    assert result.energy_kwh(first.start, first.end, "shared") == pytest.approx(first.power_w * (first.end - first.start).total_seconds() / 3_600_000)


def test_dc_ml_and_nowcast_use_only_output_cap_and_never_legacy_ac_field():
    config = site(InverterConfig("shared", output_type="dc", max_output_kw=0.5))
    assert config.inverters[0].max_ac_kw is None
    issued = START + timedelta(minutes=5)
    forecast = WeatherForecast("a", issued, (weather(), weather(START + timedelta(hours=1))))
    calls = []
    class Learner:
        def predict(self, stage_id, features, baseline_w, cap_w):
            calls.append(cap_w)
            return SimpleNamespace(power_w=9000, lower_w=8000, upper_w=10000, status="residual_no_uncertainty")
    result = ForecastEngine(config).forecast((forecast,), issued, (Observation(issued, "shared", power_w=530),), Learner())
    assert calls and set(calls) == {500}
    assert all(0 <= point.power_w <= 500 for point in result.points)
    assert result.model_status["power_nowcast:shared"].startswith("usable")
    assert result.points[0].power_w == 500
    night = weather(START.replace(hour=23))
    assert inverter_power(config, night)["shared"] == 0


@pytest.mark.parametrize("field", ["power_entity_id", "energy_entity_id"])
@pytest.mark.parametrize("other_type", ["ac", "dc"])
def test_one_meter_cannot_label_multiple_output_stages(field, other_type):
    first = InverterConfig("one", 4, **{field: "sensor.shared_measurement"})
    second = InverterConfig("two", max_ac_kw=4 if other_type == "ac" else None,
        max_output_kw=4 if other_type == "dc" else None, output_type=other_type,
        **{field: "sensor.shared_measurement"})
    with pytest.raises(ValueError, match="shared across output stages"):
        SiteConfig(49, 9, "UTC", (StringConfig("s1", "one", 3, 30, 180), StringConfig("s2", "two", 3, 30, 180)), (first, second))


def test_multiple_strings_can_share_one_controller_and_curtailment_signal_can_be_shared():
    dc = InverterConfig("shared", output_type="dc", max_output_kw=5, power_entity_id="sensor.dc_power",
        energy_entity_id="sensor.dc_energy", curtailed_entity_id="binary_sensor.common_limit")
    ac = InverterConfig("roof", 4, power_entity_id="sensor.ac_power", energy_entity_id="sensor.ac_energy",
        curtailed_entity_id="binary_sensor.common_limit")
    config = site(dc)
    assert len(config.strings) == 2 and len(config.inverters) == 1
    mixed = SiteConfig(49, 9, "UTC", (*config.strings, StringConfig("roof_string", "roof", 2, 30, 180)), (dc, ac))
    assert len(mixed.inverters) == 2
    assert mixed.inverters[0].curtailed_entity_id == mixed.inverters[1].curtailed_entity_id


def test_measurement_entity_cannot_cross_power_energy_roles_between_stages():
    first = InverterConfig("one", 4, power_entity_id="sensor.same")
    second = InverterConfig("two", output_type="dc", max_output_kw=4, energy_entity_id="sensor.same")
    with pytest.raises(ValueError, match="shared across output stages"):
        SiteConfig(49, 9, "UTC", (StringConfig("s1", "one", 3, 30, 180), StringConfig("s2", "two", 3, 30, 180)), (first, second))


def test_shared_boundary_metadata_names_have_one_core_definition():
    from custom_components.adaptive_solar.core.models import MEASUREMENT_BOUNDARIES
    assert MEASUREMENT_BOUNDARIES == {"ac": "ac_inverter_output", "dc": "dc_charge_controller_output"}
    assert InverterConfig("ac", 4).measurement_boundary == "ac_inverter_output"
    assert InverterConfig("dc", output_type="dc", max_output_kw=4).measurement_boundary == "dc_charge_controller_output"
