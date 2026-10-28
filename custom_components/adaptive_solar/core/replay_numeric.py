"""Roundoff comparison for explicitly named recomputed replay outputs only.

Raw inputs, timestamps, configuration, decisions and provenance retain their
exact comparisons. This fixed tolerance never changes a forecasting/learning
threshold or the separately declared forecast power tolerance.
"""
from __future__ import annotations

from math import isclose, isfinite

from .archive import canonical_bytes

COMPUTED_FLOAT_ABS_TOL = 1e-12
COMPUTED_FLOAT_REL_TOL = 1e-12
COMPUTED_FLOAT_POLICY = {"policy": "computed-float-roundoff-v1",
                         "abs_tol": COMPUTED_FLOAT_ABS_TOL, "rel_tol": COMPUTED_FLOAT_REL_TOL}
COMPUTED_FEATURES = frozenset({
    "baseline_w", "sun_elevation_deg", "sun_azimuth_deg", "sun_azimuth_sin", "sun_azimuth_cos",
    "day_of_year_sin", "day_of_year_cos",
})


def computed_float_equal(left, right):
    """Compare finite calculated numbers; bool and missing remain distinct."""
    if type(left) not in (int, float) or type(right) not in (int, float):
        return canonical_bytes(left) == canonical_bytes(right)
    return (isfinite(left) and isfinite(right)
            and isclose(left, right, rel_tol=COMPUTED_FLOAT_REL_TOL, abs_tol=COMPUTED_FLOAT_ABS_TOL))


def computed_mapping_equal(left, right, fields):
    """Keep identical structure and exact values outside a field allowlist."""
    if not isinstance(left, dict) or not isinstance(right, dict) or left.keys() != right.keys():
        return False
    return all(computed_float_equal(value, right[key]) if key in fields
               else canonical_bytes(value) == canonical_bytes(right[key]) for key, value in left.items())
