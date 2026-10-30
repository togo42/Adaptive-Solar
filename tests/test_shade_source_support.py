"""Shade and operative cohorts share ORIGINAL support under optional integration."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.adaptive_solar.core import engine
from custom_components.adaptive_solar.core.models import (
    InverterConfig, Observation, SiteConfig, StringConfig, WeatherForecast, WeatherPoint,
)
from custom_components.adaptive_solar.core.physics import (
    PhysicsUnavailable, clear_sky_ghi, clear_sky_ghi_mean,
)


@pytest.mark.parametrize("failure_stage", ["raw", "ghi_adjusted"])
def test_shade_cohort_keeps_original_support_before_and_after_ghi_adjustment(monkeypatch, failure_stage):
    start = datetime(2026, 6, 21, 11, tzinfo=UTC)
    end = start + timedelta(hours=1)
    issued = start + timedelta(minutes=30)
    config = SiteConfig(52, 13, "Europe/Berlin", (StringConfig("s", "i", 5, 30, 180),),
                        (InverterConfig("i", 10),), weather_models=("a", "b"), physics_substeps=4)
    original = WeatherPoint(start, end, 700, 600, 150, 20, 2, 10)
    forecasts = (WeatherForecast("a", start, (original,)),
                 WeatherForecast("b", start, (replace(original, cloud_cover_pct=37),)))
    measured_ghi = clear_sky_ghi(config, issued) * original.ghi_w_m2 / clear_sky_ghi_mean(config, start, end) * 1.1
    observations = (Observation(issued, "i", ghi_w_m2=measured_ghi),)
    interval_power = engine.interval_inverter_power
    physical_members = engine._physical_members
    phase = "operative"
    cohorts = {"operative": [], "shade": []}
    supports = {"operative": [], "shade": []}

    def evaluate_interval(cfg, source, **kwargs):
        supports[phase].append((source.start, source.end, kwargs["start"], kwargs["end"]))
        # A member can fail only after cropped-source normalization, including
        # an irradiance bound crossed solely by the adjusted-GHI evaluation.
        # The marker is cloud cover; the public integration still executes.
        adjusted = source.ghi_w_m2 > original.ghi_w_m2
        if (source.cloud_cover_pct == 37 and source.start != start
                and (failure_stage == "raw" or adjusted)):
            raise PhysicsUnavailable("unavailable_subinterval_shape")
        return interval_power(cfg, source, **kwargs)

    def evaluate_members(cfg, members, inverter_id, cell_start, cell_end, status,
                         gains=None, weight=0.0, **kwargs):
        result = physical_members(cfg, members, inverter_id, cell_start, cell_end,
                                  status, gains, weight, **kwargs)
        if kwargs.get("source_support") is not None:
            cohorts[phase].append((gains is not None, tuple(model for model, *_ in result)))
        return result

    monkeypatch.setattr(engine, "interval_inverter_power", evaluate_interval)
    monkeypatch.setattr(engine, "_physical_members", evaluate_members)
    published = engine.ForecastEngine(config).forecast(forecasts, issued, observations)
    assert published.points[0].features["ghi_regime"] == 1
    assert cohorts["operative"][:2] == [(False, ("a", "b")), (True, ("a", "b"))]
    phase = "shade"
    reference = engine.shade_reference_powers(config, forecasts, issued, "i", issued, observations)
    assert reference is not None and reference[0] < reference[1]
    assert cohorts["shade"] == cohorts["operative"][:2]
    assert supports["shade"]
    assert all(source_start == start and source_end == end and cell_start == issued and cell_end == end
               for source_start, source_end, cell_start, cell_end in supports["shade"])
    assert original.start == start and original.end == end and original.ghi_w_m2 == 700
