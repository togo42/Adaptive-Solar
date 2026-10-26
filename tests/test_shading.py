"""Direct-beam shading table, recording gates and DST quarter-hour tests."""
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from freezegun import freeze_time
from homeassistant.core import State
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_solar.coordinator import AdaptiveSolarCoordinator
from custom_components.adaptive_solar.core.engine import ForecastEngine, shade_reference_powers
from custom_components.adaptive_solar.core.models import (
    InverterConfig, Observation, SiteConfig, StringConfig, WeatherForecast, WeatherPoint,
)
from custom_components.adaptive_solar.core.physics import clear_sky_ghi, solar_position
from custom_components.adaptive_solar.core.shading import (
    BeamShadeTable, compute_beam_shade_factor, shade_bin, utc_quarter_hour,
)

T0 = datetime(2026, 6, 21, 10, 0, tzinfo=UTC)


def test_shade_bin_azimuth_wrap_and_elevation_bounds():
    assert shade_bin(0.0, 22.4) == shade_bin(360.0, 22.4) == (0, 20)
    assert shade_bin(-0.1, 22.4) == shade_bin(359.9, 22.4) == (350, 20)
    assert shade_bin(180.0, 0.0) == (180, 0)
    assert shade_bin(180.0, 89.9) == (180, 85)
    for invalid_el in (-0.01, -15.0, 90.0, 95.0, float("nan"), float("inf")):
        assert shade_bin(180.0, invalid_el) is None
    for invalid_az in (float("nan"), float("inf"), -float("inf"), True, None):
        assert shade_bin(invalid_az, 30.0) is None


def test_quarter_hour_release_replacement_eviction_and_clipping():
    table = BeamShadeTable()
    assert table.transmittance("i", 182.0, 42.0) == 1.0
    # Four distinct UTC quarter-hours remain unreleased at factor 1.0.
    for index, factor in enumerate((0.2, 0.4, 0.6, 0.8)):
        assert table.record("i", 182.0, 42.0, T0 + timedelta(minutes=15 * index), factor)
        assert table.transmittance("i", 182.0, 42.0) == 1.0
    assert table.filled_bins("i") == 0
    # Same UTC quarter-hour replaces the value without advancing the count.
    assert table.record("i", 188.0, 44.0, T0 + timedelta(minutes=45, seconds=500), 0.7)
    assert len(table.bin_samples("i", 182.0, 42.0)) == 4
    assert table.transmittance("i", 182.0, 42.0) == 1.0
    # Fifth distinct quarter-hour releases the median of stored values: (0.2, 0.4, 0.6, 0.7, 0.9) -> 0.6.
    assert table.record("i", 185.0, 41.0, T0 + timedelta(minutes=60), 0.9)
    assert table.filled_bins("i") == 1
    assert table.transmittance("i", 182.0, 42.0) == pytest.approx(0.6)
    # Out-of-bounds factors are clipped to [0, 1] before storage; non-finite rejected.
    Ring = BeamShadeTable()
    for index, raw in enumerate((-0.5, -0.1, 0.5, 1.2, 2.0)):
        Ring.record("i", 100.0, 25.0, T0 + timedelta(minutes=15 * index), raw)
    assert Ring.bin_samples("i", 100.0, 25.0) == (0.0, 0.0, 0.5, 1.0, 1.0)
    assert Ring.transmittance("i", 100.0, 25.0) == pytest.approx(0.5)
    for bad in (float("nan"), float("inf"), -float("inf"), True):
        with pytest.raises(ValueError):
            Ring.record("i", 100.0, 25.0, T0, bad)
    # 25th distinct quarter-hour evicts the oldest quarter-hour.
    evict = BeamShadeTable()
    evict.record("i", 150.0, 30.0, T0, 0.0)
    for index in range(1, 24):
        evict.record("i", 150.0, 30.0, T0 + timedelta(minutes=15 * index), 0.2 if index < 12 else 0.8)
    assert len(evict.bin_samples("i", 150.0, 30.0)) == 24
    assert evict.bin_samples("i", 150.0, 30.0)[0] == 0.0
    assert evict.transmittance("i", 150.0, 30.0) == pytest.approx(0.5)
    evict.record("i", 150.0, 30.0, T0 + timedelta(minutes=15 * 24), 0.8)
    samples = evict.bin_samples("i", 150.0, 30.0)
    assert len(samples) == 24
    assert 0.0 not in samples
    assert evict.transmittance("i", 150.0, 30.0) == pytest.approx(0.8)
    # Empty neighboring bins are never filled from neighbors.
    assert evict.transmittance("i", 160.0, 30.0) == 1.0
    assert evict.transmittance("i", 150.0, 35.0) == 1.0


@pytest.mark.parametrize("corrupt", [
    None,
    "invalid",
    {"schema": 2, "inverters": {}},
    {"schema": True, "inverters": {}},
    {"schema": 1, "inverters": []},
    {"schema": 1, "inverters": {"i": {"bad_key": []}}},
    {"schema": 1, "inverters": {"i": {"360:10": [{"quarter_hour": T0.isoformat(), "factor": 0.5}]}}},
    {"schema": 1, "inverters": {"i": {"180:90": [{"quarter_hour": T0.isoformat(), "factor": 0.5}]}}},
    {"schema": 1, "inverters": {"i": {"180:40": [{"quarter_hour": "2026-06-21T10:03:00+00:00", "factor": 0.5}]}}},
    {"schema": 1, "inverters": {"i": {"180:40": [{"quarter_hour": T0.isoformat(), "factor": 1.5}]}}},
    {"schema": 1, "inverters": {"i": {"180:40": [{"quarter_hour": T0.isoformat(), "factor": float("nan")}]}}},
    {"schema": 1, "inverters": {"unknown": {"180:40": [{"quarter_hour": T0.isoformat(), "factor": 0.5}]}}},
])
def test_serialization_roundtrip_and_corrupt_payload_fallback(corrupt):
    table = BeamShadeTable()
    for index in range(5):
        table.record("i", 184.0, 42.0, T0 + timedelta(minutes=15 * index), 0.4 + 0.05 * index)
    restored = BeamShadeTable.from_dict(table.to_dict(), inverter_ids={"i"})
    assert restored.to_dict() == table.to_dict()
    assert restored.bin_samples("i", 184.0, 42.0) == table.bin_samples("i", 184.0, 42.0)
    assert restored.transmittance("i", 184.0, 42.0) == pytest.approx(0.5)
    empty = BeamShadeTable.from_dict(corrupt, inverter_ids={"i"})
    assert empty.to_dict() == {"schema": 1, "inverters": {}}
    assert empty.transmittance("i", 184.0, 42.0) == 1.0
    # An empty/fallback table never raises in ForecastEngine.
    cfg = SiteConfig(52, 13, "Europe/Berlin", (StringConfig("s", "i", 5, 30, 180),), (InverterConfig("i", 5),))
    wf = WeatherForecast("best_match", T0, (WeatherPoint(T0, T0 + timedelta(hours=1), 700, 700, 100, 20, 2, 10),))
    result = ForecastEngine(cfg, shading=empty).forecast((wf,), T0)
    assert len(result.points) == 1 and result.points[0].power_w > 0


def test_dst_transitions_preserve_utc_quarter_hour_and_solar_position():
    zone = ZoneInfo("Europe/Berlin")
    cfg = SiteConfig(52, 13, "Europe/Berlin", (StringConfig("s", "i", 5, 30, 180),), (InverterConfig("i", 5),))
    # Spring forward: 2026-03-29 01:45 CET -> 03:00 CEST.
    spring_before = datetime(2026, 3, 29, 9, 14, tzinfo=zone)
    spring_after = datetime(2026, 3, 29, 9, 16, tzinfo=zone)
    assert utc_quarter_hour(spring_before) == datetime(2026, 3, 29, 7, 0, tzinfo=UTC)
    assert utc_quarter_hour(spring_after) == datetime(2026, 3, 29, 7, 15, tzinfo=UTC)
    # Fall back: 2026-10-25 02:10 fold=0 (CEST) vs fold=1 (CET) are distinct UTC quarter-hours.
    fall_first = datetime(2026, 10, 25, 2, 10, tzinfo=zone, fold=0)
    fall_second = datetime(2026, 10, 25, 2, 10, tzinfo=zone, fold=1)
    assert utc_quarter_hour(fall_first) != utc_quarter_hour(fall_second)
    # Daylight hours on both DST transition days map to distinct UTC quarter-hours and solar bins.
    table = BeamShadeTable()
    for day in (datetime(2026, 3, 29, 11, 0, tzinfo=UTC), datetime(2026, 10, 25, 11, 0, tzinfo=UTC)):
        sun = solar_position(cfg, day)
        assert sun.elevation_deg > 15
        for idx in range(5):
            stamp = day.astimezone(zone) + timedelta(days=idx)
            table.record("i", sun.azimuth_deg, sun.elevation_deg, stamp, 0.55)
        assert table.transmittance("i", sun.azimuth_deg, sun.elevation_deg) == pytest.approx(0.55)


async def test_coordinator_recording_gates_and_overlapping_rejections(hass):
    cfg = SiteConfig(
        52, 13, "Europe/Berlin",
        (StringConfig("wall", "i", 3.0, 45, 160), StringConfig("shed", "i", 2.0, 15, 220)),
        (InverterConfig("i", 5.0, power_entity_id="sensor.power", energy_entity_id="sensor.energy",
                        curtailed_entity_id="binary_sensor.curtailed",
                        measurement_valid_entity_id="binary_sensor.valid"),),
        irradiance_entity_id="sensor.ghi",
    )
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": cfg.to_dict()})
    entry.add_to_hass(hass)
    client = AsyncMock()
    coordinator = AdaptiveSolarCoordinator(hass, entry, cfg, client)

    def weather_for(now, *, ghi=800.0, dni=800.0, dhi=120.0):
        start = now.replace(minute=0, second=0, microsecond=0)
        return (WeatherForecast("best_match", now, (
            WeatherPoint(start, start + timedelta(hours=1), ghi, dni, dhi, 20, 2, 10),
            WeatherPoint(start + timedelta(hours=1), start + timedelta(hours=2), ghi, dni, dhi, 20, 2, 10),
        )),)

    with freeze_time(T0 - timedelta(minutes=10)):
        hass.states.async_set("binary_sensor.curtailed", "off")
        hass.states.async_set("binary_sensor.valid", "on")
        coordinator.async_start_tracking()

    # 1. Valid clear-sky observations across 5 quarter-hours release the median factor ~0.5.
    for step in range(5):
        stamp = T0 + timedelta(days=step, minutes=15)
        wf = weather_for(stamp)
        client.async_forecasts.return_value = wf
        csky = clear_sky_ghi(cfg, stamp)
        obs = (Observation(stamp, "i", ghi_w_m2=csky * 0.9),)
        p0, p1 = shade_reference_powers(cfg, wf, stamp, "i", stamp, obs)
        target_power = p0 + 0.5 * (p1 - p0)
        assert compute_beam_shade_factor(target_power, p0, p1) == pytest.approx(0.5)
        with freeze_time(stamp):
            hass.states.async_set("sensor.ghi", f"{csky * 0.9:.2f}", {"unit_of_measurement": "W/m²"})
            hass.states.async_set("sensor.power", f"{target_power:.2f}", {"unit_of_measurement": "W"})
            await coordinator._async_update_data()
        shade_diag = coordinator.learner_status["i"]["beam_shade"]
        assert shade_diag["samples"] == step + 1
        if step < 4:
            assert shade_diag["released"] is False
            assert shade_diag["transmittance"] == 1.0
            assert shade_diag["last_rejection"] == "insufficient_samples"
        else:
            assert shade_diag["released"] is True
            assert shade_diag["filled_bins"] == 1
            assert shade_diag["transmittance"] == pytest.approx(0.5, abs=1e-3)
            assert shade_diag["last_rejection"] is None

    # 2. Overlapping rejections: curtailed + low_clearness + low_beam + at_cap do not overwrite stored samples.
    stamp = T0 + timedelta(days=5, minutes=15)
    diffuse_wf = weather_for(stamp, ghi=300.0, dni=20.0, dhi=280.0)
    client.async_forecasts.return_value = diffuse_wf
    csky = clear_sky_ghi(cfg, stamp)
    with freeze_time(stamp):
        hass.states.async_set("binary_sensor.curtailed", "on")
        hass.states.async_set("sensor.ghi", f"{csky * 0.3:.2f}", {"unit_of_measurement": "W/m²"})
        hass.states.async_set("sensor.power", "4950", {"unit_of_measurement": "W"})
        await coordinator._async_update_data()
    shade_diag = coordinator.learner_status["i"]["beam_shade"]
    assert shade_diag["samples"] == 5
    assert shade_diag["released"] is True
    reasons = set(shade_diag["last_rejection"].split(";"))
    assert {"curtailed_or_invalid", "low_clearness", "low_beam", "at_cap"} <= reasons

    # 3. Unpaired GHI and Power (> 5 minutes apart) rejected with stale_or_unpaired.
    stamp = T0 + timedelta(days=6, minutes=10)
    client.async_forecasts.return_value = weather_for(stamp)
    with freeze_time(stamp):
        hass.states.async_set("binary_sensor.curtailed", "off")
        old_power_time = stamp - timedelta(minutes=7)
        hass.states.async_set("sensor.ghi", "750", {"unit_of_measurement": "W/m²"})
        hass.states.async_set(
            "sensor.power",
            "1500",
            {"unit_of_measurement": "W"},
        )
        # Force power timestamp 7 minutes earlier than GHI while still within 15 min freshness.
        hass.states.async_set(
            "sensor.power",
            State("sensor.power", "1500", {"unit_of_measurement": "W"},
                  last_updated=old_power_time, last_reported=old_power_time).state,
            {"unit_of_measurement": "W"},
        )
        coordinator._observations = lambda now: (
            Observation(old_power_time, "i", power_w=1500.0),
            Observation(stamp, "i", ghi_w_m2=750.0),
        )
        coordinator._shade_inputs = {}
        await coordinator._async_update_data()
    assert "stale_or_unpaired" in coordinator.learner_status["i"]["beam_shade"]["last_rejection"].split(";")

    # 4. Night / low elevation and missing weather reference report low_elevation and no_reference without inventing bins.
    night = T0.replace(hour=23, minute=5)
    client.async_forecasts.return_value = ()
    with freeze_time(night):
        coordinator._observations = lambda now: (
            Observation(night, "i", power_w=0.0),
            Observation(night, "i", ghi_w_m2=0.0),
        )
        await coordinator._async_update_data()
    night_diag = coordinator.learner_status["i"]["beam_shade"]
    assert night_diag["azimuth_bin_deg"] is None
    assert night_diag["elevation_bin_deg"] is None
    assert night_diag["transmittance"] == 1.0
    assert night_diag["released"] is False
    assert {"low_elevation", "no_reference"} <= set(night_diag["last_rejection"].split(";"))
    await coordinator.async_close()


def test_beam_shade_activation_prevents_residual_double_subtraction_without_mutating_archive():
    import copy
    import math
    from custom_components.adaptive_solar.coordinator import join_training
    from custom_components.adaptive_solar.core.learning import ResidualLearner

    cfg = SiteConfig(52, 13, "Europe/Berlin", (StringConfig("s", "i", 5, 30, 180),), (InverterConfig("i", 5),))
    midpoint = T0 + timedelta(minutes=30)
    sun = solar_position(cfg, midpoint)
    az_rad = math.radians(sun.azimuth_deg)
    archive = []
    intervals = []
    epoch = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
    for day in range(50):
        for hour_offset in range(6):
            start = epoch + timedelta(days=day, hours=hour_offset)
            end = start + timedelta(hours=1)
            issued = start - timedelta(hours=2)
            baseline = 2000.0
            actual = 1000.0  # 50% shade loss when baseline was unshaded (beam_shade_factor=1.0)
            archive.append({
                "issued_at": issued.isoformat(),
                "start": start.isoformat(),
                "end": end.isoformat(),
                "inverter_id": "i",
                "baseline_w": baseline,
                "power_w": baseline,
                "features": {
                    "baseline_w": baseline,
                    "sun_elevation_deg": sun.elevation_deg,
                    "sun_azimuth_deg": sun.azimuth_deg,
                    "sun_azimuth_sin": math.sin(az_rad),
                    "sun_azimuth_cos": math.cos(az_rad),
                    "day_of_year_sin": 0.5,
                    "day_of_year_cos": 0.5,
                    "temperature_c": 20.0,
                    "wind_m_s": 2.0,
                    "cloud_cover_pct": 10.0,
                    "lead_hours": 2.5,
                    "beam_shade_factor": 1.0,
                    "output_cap_w": 5000.0,
                },
            })
            intervals.append({
                "inverter_id": "i",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "observed_at": (end + timedelta(minutes=1)).isoformat(),
                "energy_kwh": actual / 1000.0,
            })
    archive_snapshot = copy.deepcopy(archive)
    as_of = epoch + timedelta(days=51)
    # Before BeamShadeTable activates, ResidualLearner learns the -1000W shade loss on unshaded baseline.
    empty_table = BeamShadeTable()
    unshaded_samples = join_training(archive, intervals, as_of=as_of, shading=empty_table)
    learner = ResidualLearner().fit(unshaded_samples, as_of)
    assert learner.status["i"]["state"] == "active"
    unshaded_pred = learner.predict("i", archive[-1]["features"], 2000.0, 5000.0)
    assert unshaded_pred.status.startswith("residual_")
    assert unshaded_pred.power_w == pytest.approx(1000.0, abs=50.0)
    # Now BeamShadeTable releases factor 0.5 for this solar bin.
    active_table = BeamShadeTable()
    for idx in range(5):
        active_table.record("i", sun.azimuth_deg, sun.elevation_deg, T0 + timedelta(minutes=15 * idx), 0.5)
    # 1. Even before refitting, passing a shaded point (beam_shade_factor=0.5, baseline=1000W) to the old learner
    # must NOT subtract another ~1000W; it falls back to the shaded physical baseline.
    shaded_features = {**archive[-1]["features"], "baseline_w": 1000.0, "beam_shade_factor": 0.5}
    guarded_pred = learner.predict("i", shaded_features, 1000.0, 5000.0)
    assert guarded_pred.status == "physics_unvalidated_shade_baseline"
    assert guarded_pred.power_w == pytest.approx(1000.0)
    # 2. join_training with active_table rejects stale unshaded rows without mutating archive.
    diag = {}
    shaded_samples = join_training(archive, intervals, diagnostics=diag, as_of=as_of, shading=active_table)
    assert shaded_samples == []
    assert diag["i"]["rejection_reasons"] == {"stale_beam_shade_baseline": 300}
    assert archive == archive_snapshot


def test_shade_reference_requires_qualified_ghi_and_scales_at_10_to_15_deg_elevation():
    cfg = SiteConfig(
        52, 13, "Europe/Berlin",
        (StringConfig("s", "i", 5, 30, 90),),
        (InverterConfig("i", 5),),
        weather_models=("icon_d2", "arome"),
    )
    # Find a morning timestamp with 10° <= solar elevation < 15° and clear-sky >= 50 W/m².
    base_day = datetime(2026, 6, 21, 4, 0, tzinfo=UTC)
    low_sun_time = None
    for minute in range(0, 240, 5):
        cand = base_day + timedelta(minutes=minute)
        sun = solar_position(cfg, cand)
        csky = clear_sky_ghi(cfg, cand)
        if 11.0 <= sun.elevation_deg <= 14.0 and csky >= 60.0:
            low_sun_time = cand
            break
    assert low_sun_time is not None
    hour_start = low_sun_time.replace(minute=0, second=0, microsecond=0)
    csky_at = clear_sky_ghi(cfg, low_sun_time)
    # Overestimated NWP irradiance (1.5x clear-sky), while actual measured GHI is 0.9x clear-sky.
    wf_icon = WeatherForecast("icon_d2", hour_start, (
        WeatherPoint(hour_start, hour_start + timedelta(hours=1), csky_at * 1.5, 450.0, 60.0, 15, 2, 10),
    ))
    wf_arome = WeatherForecast("arome", hour_start, (
        WeatherPoint(hour_start, hour_start + timedelta(hours=1), csky_at * 1.5, 450.0, 60.0, 15, 2, 10),
    ))
    obs_with_ghi = (Observation(low_sun_time, "i", ghi_w_m2=csky_at * 0.9),)
    # 1. Without GHI observation, shade_reference_powers returns None (never uncorrected NWP).
    assert shade_reference_powers(cfg, (wf_icon, wf_arome), low_sun_time, "i", low_sun_time, ()) is None
    # 2. With incomplete GHI cohort (one model has weak reference < 50 W/m²), returns None.
    wf_weak = WeatherForecast("arome", hour_start, (
        WeatherPoint(hour_start, hour_start + timedelta(hours=1), 30.0, 10.0, 25.0, 15, 2, 80),
    ))
    assert shade_reference_powers(cfg, (wf_icon, wf_weak), low_sun_time, "i", low_sun_time, obs_with_ghi) is None
    # 3. At 11-14° elevation, published GHI-nowcast stays inactive (< 15°), but shade_reference_powers
    # uses the qualified GHI measurement so an unshaded plant learns factor ~1.0 instead of NWP error.
    pub = ForecastEngine(cfg).forecast((wf_icon, wf_arome), low_sun_time, observations=obs_with_ghi)
    assert pub.model_status["irradiance"] == "ignored:low_sun_or_clear_sky"
    ref_scaled = shade_reference_powers(cfg, (wf_icon, wf_arome), low_sun_time, "i", low_sun_time, obs_with_ghi)
    assert ref_scaled is not None
    p0_scaled, p1_scaled = ref_scaled
    # Unshaded plant producing p1_scaled at the measured GHI learns factor 1.0.
    assert compute_beam_shade_factor(p1_scaled, p0_scaled, p1_scaled) == pytest.approx(1.0)


@pytest.mark.parametrize("ghi", [100.0, 2400.0])
def test_shade_reference_rejects_clipped_ghi_normalization(ghi):
    cfg = SiteConfig(52, 13, "Europe/Berlin", (StringConfig("s", "i", 5, 30, 180),),
                     (InverterConfig("i", 5),))
    wf = WeatherForecast("best_match", T0, (
        WeatherPoint(T0, T0 + timedelta(hours=1), ghi, min(ghi, 1800.0), 50, 20, 2, 10),))
    observations = (Observation(T0, "i", ghi_w_m2=700.0),)
    # The public short-lived GHI nowcast may use its bounded correction, but
    # its remaining NWP error must never enter the durable shading table.
    assert shade_reference_powers(cfg, (wf,), T0, "i", T0, observations) is None


def test_noisy_partial_shading_across_train_and_holdout_blocks_activates_without_double_subtraction():
    import math
    from custom_components.adaptive_solar.coordinator import join_training
    from custom_components.adaptive_solar.core.learning import ResidualLearner

    cfg = SiteConfig(52, 13, "Europe/Berlin", (StringConfig("s", "i", 5, 30, 180),), (InverterConfig("i", 5),))
    midpoint = T0 + timedelta(minutes=30)
    sun = solar_position(cfg, midpoint)
    az_rad = math.radians(sun.azimuth_deg)
    archive = []
    intervals = []
    epoch = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
    # Days 0..4: pre-release unshaded rows (beam_shade_factor=1.0, baseline=2000W, actual=900W).
    # Days 5..54: post-release shaded rows where rolling median fluctuates between 0.48 and 0.52.
    jitter = (0.48, 0.50, 0.52, 0.49, 0.51)
    for day in range(55):
        factor = 1.0 if day < 5 else jitter[day % len(jitter)]
        for hour_offset in range(6):
            start = epoch + timedelta(days=day, hours=hour_offset)
            end = start + timedelta(hours=1)
            issued = start - timedelta(hours=2)
            # Unshaded baseline is 2000W; shaded baseline is ~1000W; true output has an extra -100W residual (~900W).
            baseline = 2000.0 if factor == 1.0 else 400.0 + 1200.0 * factor
            actual = 900.0 if factor == 1.0 else baseline - 100.0
            archive.append({
                "issued_at": issued.isoformat(),
                "start": start.isoformat(),
                "end": end.isoformat(),
                "inverter_id": "i",
                "baseline_w": baseline,
                "power_w": baseline,
                "features": {
                    "baseline_w": baseline,
                    "sun_elevation_deg": sun.elevation_deg,
                    "sun_azimuth_deg": sun.azimuth_deg,
                    "sun_azimuth_sin": math.sin(az_rad),
                    "sun_azimuth_cos": math.cos(az_rad),
                    "day_of_year_sin": 0.5,
                    "day_of_year_cos": 0.5,
                    "temperature_c": 20.0,
                    "wind_m_s": 2.0,
                    "cloud_cover_pct": 10.0,
                    "lead_hours": 2.5,
                    "beam_shade_factor": factor,
                    "output_cap_w": 5000.0,
                },
            })
            intervals.append({
                "inverter_id": "i",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "observed_at": (end + timedelta(minutes=1)).isoformat(),
                "energy_kwh": actual / 1000.0,
            })
    active_table = BeamShadeTable()
    for idx, sample_factor in enumerate(jitter):
        active_table.record("i", sun.azimuth_deg, sun.elevation_deg, T0 + timedelta(minutes=15 * idx), sample_factor)
    as_of = epoch + timedelta(days=56)
    diag = {}
    samples = join_training(archive, intervals, diagnostics=diag, as_of=as_of, shading=active_table)
    # The 30 pre-release unshaded rows (days 0..4) are rejected; all 300 noisy shaded rows (days 5..54) are kept.
    assert diag["i"]["rejection_reasons"] == {"stale_beam_shade_baseline": 30}
    assert len(samples) == 300
    learner = ResidualLearner().fit(samples, as_of)
    assert learner.status["i"]["state"] == "active"
    pred = learner.predict("i", {**archive[-1]["features"], "baseline_w": 1000.0, "beam_shade_factor": 0.50}, 1000.0, 5000.0)
    assert pred.status == "residual_empirical_calibration"
    # Predicts ~900W (-100W residual), never double-subtracting the 1000W shade loss.
    assert pred.power_w == pytest.approx(900.0, abs=30.0)


def test_unvalidated_shaded_validation_bins_use_physics_fallback_in_holdout_and_calibration():
    import math
    from custom_components.adaptive_solar.core.learning import ResidualLearner
    from custom_components.adaptive_solar.core.models import TrainingSample

    epoch = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
    samples = []
    # 50 days * 6 hours/day = 300 hours.
    # Train (days 0..29): unshaded solar bin (azimuth 140°, elevation 35°, factor=1.0).
    # Validation (days 30..39) and Calibration (days 40..49): shaded solar bin (azimuth 210°, elevation 35°, factor=0.5)
    # that was NEVER seen in train.
    for day in range(50):
        in_holdout = day >= 30
        az_deg = 210.0 if in_holdout else 140.0
        az_rad = math.radians(az_deg)
        factor = 0.5 if in_holdout else 1.0
        for hour_offset in range(6):
            start = epoch + timedelta(days=day, hours=hour_offset)
            end = start + timedelta(hours=1)
            issued = start - timedelta(hours=2)
            baseline = 1000.0
            actual = 800.0  # -200W residual that the tree would predict if it were allowed on unsupported bins
            samples.append(TrainingSample(
                issued_at=issued,
                start=start,
                end=end,
                observed_at=end + timedelta(minutes=1),
                inverter_id="i",
                baseline_w=baseline,
                actual_w=actual,
                features={
                    "baseline_w": baseline,
                    "sun_elevation_deg": 35.0,
                    "sun_azimuth_deg": az_deg,
                    "sun_azimuth_sin": math.sin(az_rad),
                    "sun_azimuth_cos": math.cos(az_rad),
                    "day_of_year_sin": 0.5,
                    "day_of_year_cos": 0.5,
                    "temperature_c": 20.0,
                    "wind_m_s": 2.0,
                    "cloud_cover_pct": 10.0,
                    "lead_hours": 2.5,
                    "beam_shade_factor": factor,
                    "output_cap_w": 5000.0,
                },
                curtailed=False,
            ))
    learner = ResidualLearner().fit(samples, epoch + timedelta(days=51))
    # Because validation rows are in an unvalidated shaded bin, holdout evaluation falls back to physics
    # (matching predict()), so residual_validation_mae_w == physics_validation_mae_w and validation is rejected.
    assert learner.status["i"]["state"] == "rejected_validation"
    assert learner.status["i"]["residual_validation_mae_w"] == pytest.approx(
        learner.status["i"]["physics_validation_mae_w"]
    )
    assert learner.status["i"]["validation_daily_win_fraction"] == 0.0
    pred = learner.predict("i", samples[-1].features, 1000.0, 5000.0)
    assert pred.status == "physics_rejected_validation"
    assert pred.power_w == 1000.0

    # If train and validation share the supported bin (140°) and only calibration has the unsupported shaded bin (210°),
    # calibration excludes the unsupported shaded rows (calibration_target_hours == 0).
    cal_only_shaded = [
        TrainingSample(
            issued_at=s.issued_at,
            start=s.start,
            end=s.end,
            observed_at=s.observed_at,
            inverter_id=s.inverter_id,
            baseline_w=s.baseline_w,
            actual_w=s.actual_w,
            features={
                **s.features,
                "sun_azimuth_deg": 140.0,
                "sun_azimuth_sin": math.sin(math.radians(140.0)),
                "sun_azimuth_cos": math.cos(math.radians(140.0)),
                "beam_shade_factor": 1.0,
            },
            curtailed=False,
        )
        if s.start < epoch + timedelta(days=40)
        else s
        for s in samples
    ]
    cal_learner = ResidualLearner().fit(cal_only_shaded, epoch + timedelta(days=51))
    assert cal_learner.status["i"]["state"] == "active"
    assert cal_learner.status["i"]["lead_bins"]["0-6h"]["calibration_target_hours"] == 0
    assert cal_learner.status["i"]["lead_bins"]["0-6h"]["calibration_radius_w"] is None
    assert cal_learner.predict("i", samples[-1].features, 1000.0, 5000.0).status == "physics_unvalidated_shade_baseline"
