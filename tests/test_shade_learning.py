"""Reusable shading gates, accepted-sample versus release and replay policy."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.adaptive_solar.core.engine import shade_reference_powers
from custom_components.adaptive_solar.core.models import (
    InverterConfig, Observation, SiteConfig, StringConfig, WeatherForecast, WeatherPoint,
)
from custom_components.adaptive_solar.core.physics import (
    PhysicsUnavailable, SolarPosition, clear_sky_ghi, solar_position,
)
from custom_components.adaptive_solar.core.shade_learning import ShadeLearningPolicy, evaluate_shade_step
from custom_components.adaptive_solar.core.shading import BeamShadeTable

T0 = datetime(2026, 6, 21, 10, tzinfo=UTC)
SITE = SiteConfig(52, 13, "Europe/Berlin", (StringConfig("s", "i", 5, 30, 180),), (InverterConfig("i", 5),))


def step(table, *, now=T0, inputs=None, observations=(), policy=None, reference=(200.0, 2200.0), elevation=40):
    return evaluate_shade_step(
        SITE, SITE.inverters[0], (), now, observations, table,
        {"power_w": 1200.0, "power_time": now, "ghi_w_m2": 800.0, "ghi_time": now,
         "curtailed_or_invalid": False, **(inputs or {})},
        policy=policy,
        solar_position_fn=lambda *_: SolarPosition(elevation, 182, 90 - elevation),
        clear_sky_ghi_fn=lambda *_: 1000.0,
        reference_powers_fn=lambda *_: reference,
    )


def test_accepted_record_is_distinct_from_released_bin_and_same_quarter_replaces():
    table = BeamShadeTable()
    for index in range(5):
        result = step(table, now=T0 + timedelta(minutes=15 * index))
        assert result["accepted"] is True
        assert result["reasons"] == []
        assert result["factor"] == 0.5
        assert result["status"]["samples"] == index + 1
        assert result["status"]["released"] is (index == 4)
        assert result["status"]["last_rejection"] == (None if index == 4 else "insufficient_samples")
    replacement = step(table, now=T0 + timedelta(minutes=60, seconds=10), inputs={"power_w": 1800.0})
    assert replacement["accepted"] is True
    assert replacement["status"]["samples"] == 5
    assert replacement["status"]["transmittance"] == 0.5
    assert table.bin_samples("i", 182, 40) == (0.5, 0.5, 0.5, 0.5, 0.8)


@pytest.mark.parametrize(("kwargs", "reason"), [
    ({"elevation": 9.9}, "low_elevation"),
    ({"inputs": {"ghi_w_m2": 599.9}}, "low_clearness"),
    ({"inputs": {"curtailed_or_invalid": True}}, "curtailed_or_invalid"),
    ({"inputs": {"power_w": None}}, "stale_or_unpaired"),
    ({"inputs": {"ghi_time": None}}, "stale_or_unpaired"),
    ({"inputs": {"power_time": T0 - timedelta(seconds=301)}}, "stale_or_unpaired"),
    ({"inputs": {"power_w": 4900.0}}, "at_cap"),
    ({"reference": (200, 4900)}, "at_cap"),
    ({"reference": (1500, 2200)}, "low_beam"),
    ({"reference": (0, 149.9)}, "low_beam"),
    ({"reference": None}, "no_reference"),
])
def test_rejected_measurements_leave_table_unchanged(kwargs, reason):
    table = BeamShadeTable()
    table.record("other", 100, 20, T0, 0.4)
    before = deepcopy(table.to_dict())
    result = step(table, **kwargs)
    assert result["accepted"] is False
    assert reason in result["reasons"]
    assert result["factor"] is None
    assert table.to_dict() == before


def test_overlapping_rejections_are_sorted_and_keep_post_record_status_separate():
    result = step(BeamShadeTable(), inputs={"power_w": 4950, "ghi_w_m2": 100, "curtailed_or_invalid": True},
                  reference=(4500, 5000))
    assert result["reasons"] == ["at_cap", "curtailed_or_invalid", "low_beam", "low_clearness"]
    assert result["status"]["last_rejection"] == "at_cap;curtailed_or_invalid;insufficient_samples;low_beam;low_clearness"


def test_default_threshold_edges_and_factor_clipping_preserve_baseline():
    result = step(BeamShadeTable(), elevation=10, inputs={"ghi_w_m2": 600, "power_time": T0 - timedelta(seconds=300)},
                  reference=(0, 150))
    assert result["accepted"] is True
    assert result["factor"] == 1.0
    assert result["reference"]["clearness_index"] == 0.6
    below_diffuse = step(BeamShadeTable(), inputs={"power_w": 100})
    assert below_diffuse["accepted"] is True
    assert below_diffuse["factor"] == 0.0


def test_policy_candidate_recomputes_decision_without_mutating_reference_policy_or_inputs():
    baseline = ShadeLearningPolicy()
    candidate = replace(baseline, version="stricter-clearness-v1", min_clearness_index=0.9)
    inputs = {"power_w": 1200.0, "power_time": T0, "ghi_w_m2": 800.0, "ghi_time": T0,
              "curtailed_or_invalid": False, "raw_state": {"attributes": {"restored": True}}}
    original = deepcopy(inputs)
    reference = step(BeamShadeTable(), inputs=inputs, policy=baseline)
    alternate_table = BeamShadeTable()
    alternate = step(alternate_table, inputs=inputs, policy=candidate)
    assert reference["accepted"] is True
    assert alternate["accepted"] is False
    assert alternate["reasons"] == ["low_clearness"]
    assert alternate["policy_version"] == "stricter-clearness-v1"
    assert alternate["policy"]["min_clearness_index"] == 0.9
    assert baseline.min_clearness_index == 0.6
    assert inputs == original  # Raw HA evidence belongs to the caller's validator.
    assert "raw_state" not in alternate["input"]
    assert alternate_table.to_dict()["inverters"] == {}
    with pytest.raises(FrozenInstanceError):
        baseline.min_clearness_index = 0.9


@pytest.mark.parametrize("change", [
    {"version": ""}, {"version": " padded "}, {"min_clearness_index": True},
    {"min_clearness_index": float("nan")}, {"max_pair_seconds": -1},
    {"max_cap_fraction": 1.1}, {"min_beam_share": -0.1},
])
def test_invalid_policy_is_rejected(change):
    with pytest.raises(ValueError):
        ShadeLearningPolicy(**change)


@pytest.mark.parametrize("offset", [timedelta(seconds=1), -timedelta(seconds=901)])
def test_observation_fallback_excludes_future_and_stale_measurements(offset):
    table = BeamShadeTable()
    result = evaluate_shade_step(
        SITE, SITE.inverters[0], (), T0,
        (Observation(T0 + offset, "i", power_w=1200, ghi_w_m2=800),), table,
        solar_position_fn=lambda *_: SolarPosition(40, 182, 50),
        clear_sky_ghi_fn=lambda *_: 1000.0, reference_powers_fn=lambda *_: (200, 2200),
    )
    assert result["accepted"] is False
    assert result["reasons"] == ["stale_or_unpaired"]
    assert result["input"]["power_w"] is None
    assert result["input"]["ghi_w_m2"] is None
    assert table.to_dict()["inverters"] == {}


def test_observation_fallback_preserves_stage_selection_and_control_rejection():
    result = evaluate_shade_step(
        SITE, SITE.inverters[0], (), T0,
        (Observation(T0, "other", power_w=4950, ghi_w_m2=100),
         Observation(T0 - timedelta(seconds=60), "i", power_w=1200),
         Observation(T0, "i", ghi_w_m2=800), Observation(T0, "i", curtailed=True)),
        BeamShadeTable(), solar_position_fn=lambda *_: SolarPosition(40, 182, 50),
        clear_sky_ghi_fn=lambda *_: 1000.0, reference_powers_fn=lambda *_: (200, 2200),
    )
    assert result["input"]["power_w"] == 1200
    assert result["input"]["ghi_w_m2"] == 800
    assert result["input"]["power_time"] == T0 - timedelta(seconds=60)
    assert result["reasons"] == ["curtailed_or_invalid"]
    assert result["accepted"] is False


def test_reference_uses_power_instant_and_independent_ghi_clear_sky_instant():
    earlier = T0 - timedelta(seconds=120)
    calls = []

    def reference(*args):
        calls.append(args)
        return 200, 2200

    result = evaluate_shade_step(
        SITE, SITE.inverters[0], (), T0, (), BeamShadeTable(),
        {"power_w": 1200, "power_time": earlier, "ghi_w_m2": 800, "ghi_time": T0},
        solar_position_fn=lambda *_: SolarPosition(40, 182, 50),
        clear_sky_ghi_fn=lambda _, at: 1000 if at == T0 else 900,
        reference_powers_fn=reference,
    )
    assert calls[0][2:5] == (T0, "i", earlier)
    assert result["accepted"] is True
    assert result["reference"] == {
        "eval_time": earlier, "solar_azimuth_deg": 182, "solar_elevation_deg": 40,
        "clear_sky_ghi_w_m2": 900, "ghi_clear_sky_w_m2": 1000,
        "clearness_index": 0.8, "p0_w": 200, "p1_w": 2200, "beam_w": 2000,
    }


def test_unavailable_physics_retains_explicit_rejection_without_recording():
    def unavailable(*_):
        raise PhysicsUnavailable("nonfinite_test")

    result = evaluate_shade_step(
        SITE, SITE.inverters[0], (), T0, (Observation(T0, "i", power_w=1200, ghi_w_m2=800),),
        BeamShadeTable(), solar_position_fn=unavailable, reference_powers_fn=lambda *_: None,
    )
    assert result["accepted"] is False
    assert result["reasons"] == ["low_clearness", "low_elevation", "no_reference"]
    assert result["reference"]["solar_elevation_deg"] is None
    assert result["reference"]["clearness_index"] is None


@pytest.mark.parametrize("output_type", ["ac", "dc"])
def test_real_physics_reference_and_learning_match_known_half_beam_factor(output_type):
    inv = InverterConfig("i", max_output_kw=5, output_type=output_type)
    config = replace(SITE, inverters=(inv,))
    weather = (WeatherForecast("best_match", T0, (
        WeatherPoint(T0, T0 + timedelta(hours=1), 800, 800, 120, 20, 2, 10),
    )),)
    ghi = clear_sky_ghi(config, T0) * 0.9
    irradiance = Observation(T0, "i", ghi_w_m2=ghi)
    p0, p1 = shade_reference_powers(config, weather, T0, "i", T0, (irradiance,))
    power = Observation(T0, "i", power_w=p0 + 0.5 * (p1 - p0))
    table = BeamShadeTable()
    result = evaluate_shade_step(config, inv, weather, T0, (power, irradiance), table)
    assert result["accepted"] is True
    assert result["factor"] == pytest.approx(0.5)
    assert result["reference"]["p0_w"] == pytest.approx(p0)
    assert result["reference"]["p1_w"] == pytest.approx(p1)
    sun = solar_position(config, T0)
    assert table.bin_samples("i", sun.azimuth_deg, sun.elevation_deg) == pytest.approx((0.5,))
