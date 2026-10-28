"""Cross-runtime float roundoff cannot relax raw evidence or discrete gates."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from math import inf, nextafter
from unittest.mock import patch

import pytest

from custom_components.adaptive_solar.core.models import ForecastPoint, ForecastResult
from custom_components.adaptive_solar.core.physics import SolarPosition
from custom_components.adaptive_solar.core.replay import compare_results
from custom_components.adaptive_solar.core.replay_numeric import COMPUTED_FEATURES, computed_float_equal
from custom_components.adaptive_solar.core.shade_replay import _shade_decisions_same, _shade_states_same, replay_shading
from custom_components.adaptive_solar.core.shading import BeamShadeTable, MAX_SHADE_CAP_FRACTION
from tests.test_shade_learning import SITE, T0, step
from tests.test_shade_replay import NOW, bundle


def forecast(features):
    point = ForecastPoint(T0, T0 + timedelta(hours=1), "i", 1500, 1500, features=features)
    return ForecastResult(T0, (point,))


@pytest.mark.parametrize("key", sorted(COMPUTED_FEATURES))
def test_computed_features_allow_tiny_roundoff_and_reject_material_change(key):
    value = {"baseline_w": 1500.0, "sun_elevation_deg": 37.5, "sun_azimuth_deg": 182.0}.get(key, .5)
    original = forecast({key: value})
    rounded = forecast({key: nextafter(value, inf)})
    assert compare_results(original, rounded)["matched"]
    assert compare_results(original, rounded)["computed_float_comparison"]["abs_tol"] == 1e-12
    assert not compare_results(original, forecast({key: value + 1e-6}))["matched"]


@pytest.mark.parametrize("key", ["ghi_regime", "source_partial_at_issue", "beam_shade_factor", "output_cap_w",
                                "lead_hours", "ghi_observation_age_seconds", "temperature_c", "unknown_feature"])
def test_all_other_feature_values_stay_exact_even_for_one_ulp(key):
    assert not compare_results(forecast({key: 1.0}), forecast({key: nextafter(1.0, inf)}))["matched"]
    assert not compare_results(forecast({key: 1.0}), forecast({key: 1.0, "extra": 1.0}))["matched"]


def test_forecast_power_tolerance_and_time_support_stay_independent():
    original = forecast({"sun_elevation_deg": 30.0})
    changed = replace(original, points=(replace(original.points[0], power_w=1500.0 + 2e-6),))
    assert not compare_results(original, changed)["matched"]
    shifted = replace(original, issued_at=T0 + timedelta(microseconds=1))
    assert not compare_results(original, shifted)["matched"]


@pytest.mark.parametrize(("left", "right"), [(True, 1), (False, 0), (None, 0), (inf, inf), (float("nan"), 0)])
def test_computed_float_comparison_does_not_equate_missing_boolean_or_nonfinite(left, right):
    assert not computed_float_equal(left, right)


@pytest.mark.parametrize("section,key", [("reference", "solar_elevation_deg"), ("reference", "p0_w"),
                                        ("reference", "p1_w"), ("reference", "clearness_index"),
                                        ("status", "candidate_transmittance"), ("status", "transmittance"),
                                        ("status", "daily_mad")])
def test_shade_calculated_diagnostics_allow_only_tiny_roundoff(section, key):
    original = {"i": step(BeamShadeTable())}
    rounded = deepcopy(original)
    rounded["i"][section][key] = nextafter(original["i"][section][key], inf)
    assert _shade_decisions_same(original, rounded)
    rounded["i"][section][key] += 1e-6
    assert not _shade_decisions_same(original, rounded)


@pytest.mark.parametrize("section,key,value", [
    ("input", "power_w", nextafter(1200.0, inf)),
    ("policy", "min_clearness_index", nextafter(.6, inf)),
    ("status", "azimuth_bin_deg", nextafter(180.0, inf)),
    ("status", "samples", nextafter(1.0, inf)),
    ("status", "released", True),
    ("reference", "eval_time", T0 + timedelta(microseconds=1)),
])
def test_shade_inputs_policy_bins_counts_gates_and_clocks_remain_exact(section, key, value):
    original = {"i": step(BeamShadeTable())}
    changed = deepcopy(original)
    changed["i"][section][key] = value
    assert not _shade_decisions_same(original, changed)


def test_one_ulp_at_cap_boundary_does_not_hide_a_changed_learning_decision():
    limit = MAX_SHADE_CAP_FRACTION * SITE.inverters[0].output_cap_w
    blocked = step(BeamShadeTable(), reference=(200, limit))
    admitted = step(BeamShadeTable(), reference=(200, nextafter(limit, -inf)))
    assert blocked["accepted"] is False and admitted["accepted"] is True
    assert not _shade_decisions_same({"i": blocked}, {"i": admitted})


def test_shade_learned_factors_round_but_structure_availability_and_legacy_inputs_do_not():
    table = BeamShadeTable()
    for index in range(6):
        at = T0 + timedelta(days=index // 5, minutes=15 * (index % 5))
        table.record("i", 182, 40, at, .5, as_of=at)
    original = table.to_dict()
    assert original["released"]
    rounded = deepcopy(original)
    rounded["inverters"]["i"]["180:40"][0]["factor"] = nextafter(.5, inf)
    rounded["released"]["i"]["180:40"][0]["factor"] = nextafter(.5, inf)
    assert _shade_states_same(original, rounded)
    rounded["inverters"]["i"]["180:40"][0]["available_at"] = (T0 + timedelta(microseconds=1)).isoformat()
    assert not _shade_states_same(original, rounded)
    changed = deepcopy(original)
    changed["released"]["i"]["180:40"][0]["factor"] += 1e-6
    assert not _shade_states_same(original, changed)
    changed = deepcopy(original)
    changed["inverters"]["i"]["180:40"].pop()
    assert not _shade_states_same(original, changed)
    legacy = {"schema": 3, "inverters": {}, "released": {}, "unqualified_legacy": {"i": {"180:40": [{"factor": .5}]}}}
    changed = deepcopy(legacy)
    changed["unqualified_legacy"]["i"]["180:40"][0]["factor"] = nextafter(.5, inf)
    assert not _shade_states_same(legacy, changed)


def test_multiday_replay_preserves_learned_state_continuity_with_tiny_roundoff(tmp_path):
    times = [NOW + timedelta(minutes=15 * index) for index in range(5)] + [NOW + timedelta(days=1)]
    target = "custom_components.adaptive_solar.core.shade_learning."
    with patch("tests.test_shade_replay.clear_sky_ghi", return_value=1000), \
         patch(target + "solar_position", return_value=SolarPosition(40, 182, 50)), \
         patch(target + "clear_sky_ghi", return_value=1000), \
         patch(target + "shade_reference_powers", return_value=(200., 2200.)):
        events, dependencies = bundle(tmp_path, times=times)
        with patch(target + "shade_reference_powers", return_value=(200., nextafter(2200., inf))):
            result = replay_shading(events, dependencies)
    assert result["baseline"]["accepted"]
    assert result["step_count"] == 6
    assert all(row["baseline"]["decisions_match"] and row["baseline"]["state_match"] for row in result["steps"])
    assert result["steps"][-1]["baseline"]["decisions"]["i"]["status"]["released"]
    assert result["computed_float_comparison"]["rel_tol"] == 1e-12


def test_computed_tolerance_near_zero_and_scaled_values_has_explicit_boundaries():
    assert computed_float_equal(0.0, 1e-12)
    assert not computed_float_equal(0.0, 1.01e-12)
    assert computed_float_equal(1500.0, 1500.0 + 1e-9)
    assert not computed_float_equal(1500.0, 1500.0 + 2e-9)
