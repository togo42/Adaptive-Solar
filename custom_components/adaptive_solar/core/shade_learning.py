"""One reproducible, HA-independent direct-beam shading learning decision.

The default policy preserves the coordinator's original learning gates. Explicit
``stage_input`` is already normalized by the caller, including freshness and
restored/control checks; this function does not reinterpret raw HA states.
Replays must validate that input provenance before calling the same step. Only
the supplied shade table is mutated, and only for an accepted measurement.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Callable, Mapping

from ..const import SENSOR_MAX_AGE_SECONDS
from .engine import shade_reference_powers
from .models import InverterConfig, Observation, SiteConfig, finite_number
from .physics import PhysicsUnavailable, clear_sky_ghi, solar_position
from .shading import (
    MAX_SHADE_CAP_FRACTION, MAX_SHADE_PAIR_SECONDS, MIN_SHADE_BEAM_ABS_W,
    MIN_SHADE_BEAM_CAP_FRACTION, MIN_SHADE_BEAM_SHARE, MIN_SHADE_CLEARNESS_INDEX,
    MIN_SHADE_CLEAR_SKY_W_M2, MIN_SHADE_ELEVATION_DEG,
    BeamShadeTable, compute_beam_shade_factor, shade_bin,
)


@dataclass(frozen=True)
class ShadeLearningPolicy:
    """Versioned gate parameters; table bins, retention and release stay fixed.

    ``version`` names the decision algorithm. Full parameters are included in
    every decision so a changed candidate threshold remains distinguishable.
    """

    version: str = "beam-shade-learning-v2"
    min_elevation_deg: float = MIN_SHADE_ELEVATION_DEG
    min_clear_sky_w_m2: float = MIN_SHADE_CLEAR_SKY_W_M2
    min_clearness_index: float = MIN_SHADE_CLEARNESS_INDEX
    min_beam_share: float = MIN_SHADE_BEAM_SHARE
    min_beam_abs_w: float = MIN_SHADE_BEAM_ABS_W
    min_beam_cap_fraction: float = MIN_SHADE_BEAM_CAP_FRACTION
    max_cap_fraction: float = MAX_SHADE_CAP_FRACTION
    max_pair_seconds: float = MAX_SHADE_PAIR_SECONDS

    def __post_init__(self) -> None:
        if not isinstance(self.version, str) or not self.version.strip() or self.version != self.version.strip():
            raise ValueError("policy version must be a nonempty string")
        for name, high in (
            ("min_elevation_deg", 90), ("min_clear_sky_w_m2", 1600),
            ("min_clearness_index", None), ("min_beam_share", 1),
            ("min_beam_abs_w", None), ("min_beam_cap_fraction", 1),
            ("max_cap_fraction", 1), ("max_pair_seconds", None),
        ):
            object.__setattr__(self, name, finite_number(getattr(self, name), name, 0, high))


def evaluate_shade_step(
    config: SiteConfig,
    inv: InverterConfig,
    forecasts,
    now: datetime,
    observations: tuple[Observation, ...],
    shading: BeamShadeTable,
    stage_input: Mapping[str, Any] | None = None,
    *,
    policy: ShadeLearningPolicy | None = None,
    solar_position_fn: Callable | None = None,
    clear_sky_ghi_fn: Callable | None = None,
    reference_powers_fn: Callable | None = None,
) -> dict[str, Any]:
    """Evaluate and optionally record one measurement, retaining decision inputs.

    ``accepted`` describes recording, while ``status`` describes the current
    solar bin. Thus an accepted first sample still has ``insufficient_samples``
    in its status. Datetimes remain datetimes for the caller's serialization.
    Injectable physics functions preserve existing coordinator test seams.
    """
    policy = policy if policy is not None else ShadeLearningPolicy()
    sun_at = solar_position_fn if solar_position_fn is not None else solar_position
    clear_at = clear_sky_ghi_fn if clear_sky_ghi_fn is not None else clear_sky_ghi
    reference_at = reference_powers_fn if reference_powers_fn is not None else shade_reference_powers
    observations = tuple(observations)
    if stage_input is not None:
        raw_power = stage_input.get("power_w")
        power_time = stage_input.get("power_time")
        ghi = stage_input.get("ghi_w_m2")
        ghi_time = stage_input.get("ghi_time")
        curtailed_or_invalid = bool(stage_input.get("curtailed_or_invalid"))
    else:
        own = [o for o in observations if o.inverter_id == inv.id]
        ordered = sorted(own, key=lambda item: item.time, reverse=True)
        power_obs = next(
            (o for o in ordered if o.power_w is not None
             and 0 <= (now - o.time).total_seconds() <= SENSOR_MAX_AGE_SECONDS), None,
        )
        ghi_obs = next(
            (o for o in ordered if o.ghi_w_m2 is not None
             and 0 <= (now - o.time).total_seconds() <= 300), None,
        )
        raw_power = power_obs.power_w if power_obs is not None else None
        power_time = power_obs.time if power_obs is not None else None
        ghi = ghi_obs.ghi_w_m2 if ghi_obs is not None else None
        ghi_time = ghi_obs.time if ghi_obs is not None else None
        curtailed_or_invalid = any(
            o.curtailed or (o.power_w is not None and o.power_w > inv.output_cap_w * 1.1)
            for o in own
        )
    inputs = {
        "power_w": raw_power, "power_time": power_time,
        "ghi_w_m2": ghi, "ghi_time": ghi_time,
        "curtailed_or_invalid": curtailed_or_invalid,
    }
    reasons: set[str] = set()
    if curtailed_or_invalid:
        reasons.add("curtailed_or_invalid")
    if (raw_power is None or power_time is None or ghi is None or ghi_time is None
            or abs((power_time - ghi_time).total_seconds()) > policy.max_pair_seconds):
        reasons.add("stale_or_unpaired")
    eval_time = power_time if power_time is not None else (ghi_time if ghi_time is not None else now)
    try:
        eval_sun = sun_at(config, eval_time)
        eval_clear_sky = clear_at(config, eval_time)
    except PhysicsUnavailable:
        eval_sun = None
        eval_clear_sky = 0.0
    if (eval_sun is None or eval_sun.elevation_deg < policy.min_elevation_deg
            or eval_clear_sky < policy.min_clear_sky_w_m2):
        reasons.add("low_elevation")
    ghi_clear_sky = None
    clearness_index = None
    if ghi is not None and ghi_time is not None:
        try:
            ghi_clear_sky = eval_clear_sky if ghi_time == eval_time else clear_at(config, ghi_time)
        except PhysicsUnavailable:
            ghi_clear_sky = 0.0
        clearness_index = ghi / ghi_clear_sky if ghi_clear_sky > 0.0 else None
        if ghi_clear_sky <= 0.0 or clearness_index < policy.min_clearness_index:
            reasons.add("low_clearness")
    ref_powers = reference_at(config, forecasts, now, inv.id, eval_time, observations)
    cap_limit = policy.max_cap_fraction * inv.output_cap_w
    if raw_power is not None and raw_power <= inv.output_cap_w * 1.1 and raw_power >= cap_limit:
        reasons.add("at_cap")
    p0_w = p1_w = beam_w = factor = None
    accepted = False
    if ref_powers is None:
        reasons.add("no_reference")
    else:
        p0_w, p1_w = ref_powers
        beam_w = p1_w - p0_w
        min_beam_w = max(policy.min_beam_abs_w, policy.min_beam_cap_fraction * inv.output_cap_w)
        if beam_w < policy.min_beam_share * p1_w or beam_w < min_beam_w:
            reasons.add("low_beam")
        if p1_w >= cap_limit:
            reasons.add("at_cap")
        if not reasons and eval_sun is not None and power_time is not None:
            factor = compute_beam_shade_factor(raw_power, p0_w, p1_w)
            accepted = shading.record(inv.id, eval_sun.azimuth_deg, eval_sun.elevation_deg, power_time, factor, as_of=now)
    gate_reasons = sorted(reasons)
    try:
        now_sun = eval_sun if eval_time == now else sun_at(config, now)
    except PhysicsUnavailable:
        now_sun = None
    az_now = now_sun.azimuth_deg if now_sun is not None else None
    el_now = now_sun.elevation_deg if now_sun is not None else None
    if shade_bin(az_now, el_now) is not None:
        status = shading.status_for(inv.id, az_now, el_now, as_of=now)
        if not status["released"]:
            reasons.add(status["release_reason"])
    elif eval_sun is not None and shade_bin(eval_sun.azimuth_deg, eval_sun.elevation_deg) is not None:
        status = shading.status_for(inv.id, eval_sun.azimuth_deg, eval_sun.elevation_deg, as_of=now)
        if not status["released"]:
            reasons.add(status["release_reason"])
    last_rejection = ";".join(sorted(reasons)) if reasons else None
    return {
        "schema": 1,
        "policy_version": policy.version,
        "policy": asdict(policy),
        "accepted": accepted,
        "reasons": gate_reasons,
        "status": shading.status_for(inv.id, az_now, el_now, as_of=now, last_rejection=last_rejection),
        "input": inputs,
        "reference": {
            "eval_time": eval_time,
            "solar_azimuth_deg": eval_sun.azimuth_deg if eval_sun is not None else None,
            "solar_elevation_deg": eval_sun.elevation_deg if eval_sun is not None else None,
            "clear_sky_ghi_w_m2": eval_clear_sky,
            "ghi_clear_sky_w_m2": ghi_clear_sky,
            "clearness_index": clearness_index,
            "p0_w": p0_w, "p1_w": p1_w, "beam_w": beam_w,
        },
        "factor": factor,
    }
