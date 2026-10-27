"""Conservative Ecowitt-style GHI input and short geometry-normalized nowcast.

Synthetic tests establish behavior and provenance, never measured accuracy.
"""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from freezegun import freeze_time
from homeassistant.core import State
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_solar.coordinator import AdaptiveSolarCoordinator, state_number
from custom_components.adaptive_solar.core.engine import ForecastEngine, _irradiance_gains, _irradiance_weight
from custom_components.adaptive_solar.core.models import InverterConfig, Observation, SiteConfig, StringConfig, WeatherForecast, WeatherPoint
from custom_components.adaptive_solar.core.physics import clear_sky_ghi, clear_sky_ghi_mean, solar_position

NOW = datetime(2026, 6, 21, 10, 5, tzinfo=UTC)
START = NOW.replace(minute=0)


def site(*, entity=None, cap=20, models=("a",)):
    return SiteConfig(52, 13, "Europe/Berlin", (StringConfig("s", "i", 5, 30, 180),), (InverterConfig("i", cap),), weather_models=models, irradiance_entity_id=entity)


def weather(start=START, *, ghi=600, duration=1):
    return WeatherPoint(start, start + timedelta(hours=duration), ghi, ghi * 0.8, ghi * 0.3, 20, 2, 30)


def forecasts(now=NOW, *, model="a", points=None):
    start = now.replace(minute=0)
    return (WeatherForecast(model, now, tuple(points or [weather(start + timedelta(hours=hour)) for hour in (0, 1, 2, 3, 24)])),)


def observation(value, *, time=NOW):
    return Observation(time, "i", ghi_w_m2=value)


def test_optional_config_and_observation_keep_old_json_and_positional_contracts():
    config = site()
    old = config.to_dict()
    old.pop("irradiance_entity_id")
    assert SiteConfig.from_dict(old).irradiance_entity_id is None
    bound = replace(config, irradiance_entity_id="sensor.test_irradiance")
    assert SiteConfig.from_dict(json.loads(json.dumps(bound.to_dict()))) == bound
    old_observation = Observation(NOW, "i", 1500, 20, 2, True)
    assert old_observation.curtailed is True and old_observation.ghi_w_m2 is None
    assert Observation(NOW, "i", None, None, None, False, 600).ghi_w_m2 == 600
    for invalid in (True, -1, 1601, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            observation(invalid)


@pytest.mark.parametrize("unit,value,expected", [("W/m²", "650", 650), ("W/m2", "650", 650), ("kW/m²", "0.65", 650), ("kW/m2", "0.65", 650), ("W/m²", "0", 0)])
def test_explicit_irradiance_units_and_measured_zero(unit, value, expected):
    with freeze_time(NOW):
        assert state_number(State("sensor.test", value, {"unit_of_measurement": unit}), NOW, "irradiance") == expected


@pytest.mark.parametrize("value,unit", [("unknown", "W/m²"), ("unavailable", "W/m²"), ("nan", "W/m²"), ("inf", "W/m²"), ("-1", "W/m²"), ("1601", "W/m²"), ("600", "lx"), ("600", "W"), ("600", None)])
def test_unknown_invalid_and_illuminance_values_are_never_global_irradiance(value, unit):
    with freeze_time(NOW):
        assert state_number(State("sensor.test", value, {"unit_of_measurement": unit}), NOW, "irradiance") is None


@pytest.mark.parametrize("offset", [-301, 1])
def test_stale_and_future_real_report_times_rejected(offset):
    stamp = NOW + timedelta(seconds=offset)
    state = State("sensor.test", "0", {"unit_of_measurement": "W/m²"}, last_updated=stamp, last_reported=stamp)
    assert state_number(state, NOW, "irradiance") is None
    engine = ForecastEngine(site())
    baseline = engine.forecast(forecasts(), NOW)
    result = engine.forecast(forecasts(), NOW, (observation(800, time=stamp),))
    assert result.points == baseline.points
    assert result.model_status["irradiance"] == ("ignored:stale" if offset < 0 else "ignored:future")


def test_more_ghi_increases_short_term_power_and_leaves_later_hours_exactly_unchanged():
    engine = ForecastEngine(site())
    baseline = engine.forecast(forecasts(), NOW)
    dark = engine.forecast(forecasts(), NOW, (observation(250),))
    bright = engine.forecast(forecasts(), NOW, (observation(1000),))
    assert 0 < dark.points[0].power_w < baseline.points[0].power_w < bright.points[0].power_w
    assert bright.points[1].features["ghi_nowcast_gain"] - 1 < bright.points[0].features["ghi_nowcast_gain"] - 1
    assert bright.points[2:] == baseline.points[2:]
    assert dark.model_status["irradiance"] == bright.model_status["irradiance"] == "usable:haurwitz_normalized"
    assert bright.points[0].features["ghi_observation_w_m2"] == 1000
    assert bright.points[0].features["ghi_observation_age_seconds"] == 0


def test_morning_instant_matches_hourly_clearness_without_solar_motion_bias():
    config = site()
    now = NOW.replace(hour=5, minute=1)
    start = now.replace(minute=0)
    instantaneous = clear_sky_ghi(config, now) * 0.7
    mean = clear_sky_ghi_mean(config, start, start + timedelta(hours=1)) * 0.7
    assert solar_position(config, now).elevation_deg >= 15
    assert instantaneous < mean * 0.9  # naive instant/hourly ratio would bias down
    source = forecasts(now, points=[weather(start, ghi=mean)])
    engine = ForecastEngine(config)
    expected = engine.forecast(source, now)
    result = engine.forecast(source, now, (observation(instantaneous, time=now),))
    assert result.points[0].power_w == pytest.approx(expected.points[0].power_w, rel=1e-12)
    assert result.points[0].features["ghi_nowcast_gain"] == pytest.approx(1)


@pytest.mark.parametrize("hour", [3, 4, 23])
def test_low_sun_and_night_are_passive(hour):
    now = NOW.replace(hour=hour)
    source = forecasts(now)
    engine = ForecastEngine(site())
    baseline = engine.forecast(source, now)
    result = engine.forecast(source, now, (observation(600, time=now),))
    assert result.points == baseline.points
    assert result.model_status["irradiance"] == "ignored:low_sun_or_clear_sky"
    if hour == 23:
        assert result.points[0].power_w == 0


def test_zero_at_high_sun_is_bounded_downward_not_stretched_over_days():
    engine = ForecastEngine(site())
    baseline = engine.forecast(forecasts(), NOW)
    result = engine.forecast(forecasts(), NOW, (observation(0),))
    assert 0 < result.points[0].power_w < baseline.points[0].power_w
    assert 0.35 <= result.points[0].features["ghi_nowcast_gain"] <= 1
    assert result.points[-1] == baseline.points[-1]


def test_original_weather_reference_before_issue_and_fail_closed_when_missing_or_weak():
    now = START + timedelta(minutes=2)
    observed = START - timedelta(minutes=1)
    previous = weather(START - timedelta(hours=1))
    current = weather(START)
    source = forecasts(now, points=[previous, current])
    engine = ForecastEngine(site())
    result = engine.forecast(source, now, (observation(950, time=observed),))
    assert result.points[0].features["ghi_nowcast_gain"] > 1
    missing = engine.forecast(forecasts(now, points=[current]), now, (observation(950, time=observed),))
    assert missing.model_status["irradiance"] == "ignored:no_reference_interval"
    weak = engine.forecast(forecasts(now, points=[weather(START, ghi=0)]), now, (observation(950, time=now),))
    assert weak.model_status["irradiance"] == "ignored:weak_reference"
    assert weak.points[0].power_w == 0


def test_reference_clearness_uses_original_interval_before_ensemble_splitting():
    config = site(models=("a", "b"))
    # GHI values represent identical 70%-clear weather over different grids.
    hourly = replace(weather(), ghi_w_m2=clear_sky_ghi_mean(config, START, START + timedelta(hours=1)) * 0.7)
    first = replace(weather(duration=0.5), ghi_w_m2=clear_sky_ghi_mean(config, START, START + timedelta(minutes=30)) * 0.7)
    second = replace(weather(START + timedelta(minutes=30), duration=0.5), ghi_w_m2=clear_sky_ghi_mean(config, START + timedelta(minutes=30), START + timedelta(hours=1)) * 0.7)
    arms = {"a": WeatherForecast("a", NOW, (hourly,)), "b": WeatherForecast("b", NOW, (first, second))}
    _, gains, status = _irradiance_gains(config, arms, (observation(clear_sky_ghi(config, NOW) * 0.7),), NOW)
    assert status.startswith("usable")
    assert gains == pytest.approx({"a": 1, "b": 1})
    baseline = ForecastEngine(config).forecast(tuple(arms.values()), NOW)
    result = ForecastEngine(config).forecast(tuple(arms.values()), NOW, (observation(clear_sky_ghi(config, NOW) * 0.7),))
    assert [point.power_w for point in result.points] == pytest.approx([point.power_w for point in baseline.points])


def test_common_multiplier_keeps_direct_diffuse_proportions_and_final_ac_cap(monkeypatch):
    from custom_components.adaptive_solar.core import engine as module
    from custom_components.adaptive_solar.core.physics import inverter_power

    seen = []
    def inspect(config, point, **kwargs):
        seen.append(point)
        return inverter_power(config, point, **kwargs)
    monkeypatch.setattr(module, "inverter_power", inspect)
    config = site(cap=0.5)
    result = ForecastEngine(config).forecast(forecasts(), NOW, (observation(1600),))
    original = weather()
    scaled = next(point for point in seen if point.ghi_w_m2 > original.ghi_w_m2)
    assert scaled.dni_w_m2 / scaled.ghi_w_m2 == pytest.approx(original.dni_w_m2 / original.ghi_w_m2)
    assert scaled.dhi_w_m2 / scaled.ghi_w_m2 == pytest.approx(original.dhi_w_m2 / original.ghi_w_m2)
    assert all(0 <= point.power_w <= 500 for point in result.points)


def test_power_nowcast_residual_uses_contemporaneous_ghi_instant_reference():
    # An hourly forecast mean is not a momentary meter value. Form a physical
    # instant with the measured GHI and the same NWP component time shapes.
    from custom_components.adaptive_solar.core.physics import instantaneous_weather, inverter_power
    engine = ForecastEngine(site())
    ghi = observation(1000)
    adjusted = engine.forecast(forecasts(), NOW, (ghi,))
    proxy = instantaneous_weather(site(), weather(), NOW)
    gain = max(0.35, min(1.65, ghi.ghi_w_m2 / proxy.ghi_w_m2))
    proxy = replace(proxy, ghi_w_m2=proxy.ghi_w_m2 * gain, dni_w_m2=proxy.dni_w_m2 * gain, dhi_w_m2=proxy.dhi_w_m2 * gain)
    power = Observation(NOW, "i", power_w=inverter_power(site(), proxy, at=NOW)["i"])
    together = engine.forecast(forecasts(), NOW, (ghi, power))
    power_only = engine.forecast(forecasts(), NOW, (power,))
    for point, ghi_point, nwp_point in zip(together.points, adjusted.points, power_only.points, strict=True):
        assert point == (ghi_point if point.features["ghi_regime"] else nwp_point)


def test_ghi_influence_removes_uncalibrated_ml_bounds_only_in_its_short_window():
    class Learner:
        def predict(self, inverter, features, baseline, cap):
            return SimpleNamespace(power_w=baseline, lower_w=max(0, baseline - 100), upper_w=min(cap, baseline + 100), status="residual_empirical_calibration")
    engine = ForecastEngine(site())
    result = engine.forecast(forecasts(), NOW, (observation(1000),), Learner())
    assert result.points[0].lower_w is result.points[0].upper_w is None
    assert result.points[-1].lower_w is not None
    assert result.model_status["i"] == "residual_empirical_calibration;residual_no_uncertainty"
    only = engine.forecast(forecasts(points=[weather()]), NOW, (observation(1000),), Learner())
    assert only.model_status["i"] == "residual_no_uncertainty"


def test_decay_integrates_only_available_future_and_never_revives_after_cutoff():
    first = _irradiance_weight(START, START + timedelta(hours=1), NOW, NOW)
    later = _irradiance_weight(START + timedelta(hours=1), START + timedelta(hours=2), NOW, NOW)
    assert 0 < later < first < 1
    assert _irradiance_weight(NOW + timedelta(minutes=90), NOW + timedelta(minutes=100), NOW, NOW) == 0


async def test_ha_reports_keep_own_timestamp_stale_zero_ignored_and_dst_is_real(hass):
    config = site(entity="sensor.test_irradiance")
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    coordinator = AdaptiveSolarCoordinator(hass, entry, config, AsyncMock())
    local = datetime(2026, 10, 25, 2, 30, tzinfo=ZoneInfo("Europe/Berlin"), fold=1)
    stamp = local.astimezone(UTC)
    with freeze_time(stamp - timedelta(hours=1)):
        hass.states.async_set("sensor.test_irradiance", "0", {"unit_of_measurement": "W/m²", "device_class": "irradiance"})
    with freeze_time(stamp):
        assert not coordinator._observations(stamp)
        assert coordinator.input_quality["irradiance"].startswith("ignored")
        hass.states.async_set("sensor.test_irradiance", "0", {"unit_of_measurement": "W/m²", "device_class": "irradiance"})
        observations = coordinator._observations(stamp)
        assert len(observations) == 1
        assert observations[0].time == stamp
        assert observations[0].ghi_w_m2 == 0
    await coordinator.async_close()


async def test_default_none_preserves_old_history_fingerprint_and_native_selector_is_editable(hass, enable_custom_integrations):
    config = site()
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    coordinator = AdaptiveSolarCoordinator(hass, entry, config, AsyncMock())
    old_dict = config.to_dict()
    old_dict.pop("irradiance_entity_id")
    assert coordinator._fingerprint == hashlib.sha256(json.dumps(old_dict, sort_keys=True).encode()).hexdigest()[:16]
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    field = next(value for key, value in flow["data_schema"].schema.items() if key.schema == "irradiance_entity_id")
    assert field.config["filter"] == [{"domain": ["sensor"], "device_class": ["irradiance"]}]
    values = {key: value for key, value in config.to_dict().items() if key not in ("strings", "inverters", "temperature_entity_id", "wind_entity_id")}
    values["irradiance_entity_id"] = "sensor.test_irradiance"
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], values)
    inverter = {key: value for key, value in config.to_dict()["inverters"][0].items() if value is not None}
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {**inverter, "add_another": False})
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {**config.to_dict()["strings"][0], "add_another": False})
    assert flow["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options["site"]["irradiance_entity_id"] == "sensor.test_irradiance"
    await coordinator.async_close()


async def test_only_preissued_ghi_features_are_archived_and_never_backfilled(hass):
    config = site(entity="sensor.test_irradiance")
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    coordinator = AdaptiveSolarCoordinator(hass, entry, config, AsyncMock())
    engine = ForecastEngine(config)
    initial = engine.forecast(forecasts(), NOW, (observation(1000),))
    coordinator._archive_result(initial, available_at=initial.issued_at)
    archived = [dict(row) for row in coordinator.archive]
    influenced = [row for row in archived if "ghi_observation_w_m2" in row["features"]]
    assert influenced
    assert all(row["features"]["ghi_observation_w_m2"] == 1000 for row in influenced)
    assert all(datetime.fromisoformat(row["issued_at"]) <= datetime.fromisoformat(row["start"]) for row in influenced)
    tomorrow = NOW + timedelta(days=1)
    stale = engine.forecast(forecasts(tomorrow), tomorrow, (observation(1000),))
    assert all("ghi_observation_w_m2" not in point.features for point in stale.points)
    coordinator._archive_result(stale, available_at=stale.issued_at)
    assert all(row in coordinator.archive for row in influenced)
    await coordinator.async_close()


def test_hourly_means_have_bounded_window_integration_without_a_false_instant_claim():
    engine = ForecastEngine(site())
    baseline = engine.forecast(forecasts(), NOW)
    result = engine.forecast(forecasts(), NOW, (observation(1000),))
    cutoff = NOW + timedelta(minutes=90)
    # The 11-12 source hour overlaps the integration window until 11:35.
    # Its mean is still the published value at 11:45; that is not an instant.
    assert result.power_at(cutoff + timedelta(minutes=10), "i") > baseline.power_at(cutoff + timedelta(minutes=10), "i")
    # The first source hour with no overlap is exactly the original forecast.
    assert result.power_at(START + timedelta(hours=2, minutes=15), "i") == baseline.power_at(START + timedelta(hours=2, minutes=15), "i")


def test_ghi_nowcast_with_released_beam_shade_scales_direct_only():
    from custom_components.adaptive_solar.core.shading import BeamShadeTable

    cfg = site()
    midpoint = NOW + (START + timedelta(hours=1) - NOW) / 2
    sun = solar_position(cfg, midpoint)
    table = BeamShadeTable()
    for idx in range(5):
        table.record("i", sun.azimuth_deg, sun.elevation_deg, NOW - timedelta(days=idx), 0.5, as_of=NOW)
    unshaded = ForecastEngine(cfg).forecast(forecasts(), NOW, (observation(900),))
    shaded = ForecastEngine(cfg, shading=table).forecast(forecasts(), NOW, (observation(900),))
    assert shaded.points[0].features["ghi_regime"] == 1.0
    assert 0 < shaded.points[0].power_w < unshaded.points[0].power_w
    # Purely diffuse NWP hour scaled by GHI observation keeps diffuse power unchanged under beam shading.
    diffuse_pt = WeatherPoint(START, START + timedelta(hours=1), 600, 0, 600, 20, 2, 100)
    diffuse_fc = forecasts(points=[diffuse_pt])
    shaded_diff = ForecastEngine(cfg, shading=table).forecast(diffuse_fc, NOW, (observation(600),))
    unshaded_diff = ForecastEngine(cfg).forecast(diffuse_fc, NOW, (observation(600),))
    assert [(p.start, p.end, p.baseline_w, p.power_w) for p in shaded_diff.points] == [
        (p.start, p.end, p.baseline_w, p.power_w) for p in unshaded_diff.points
    ]
    assert shaded_diff.points[0].features["beam_shade_factor"] == pytest.approx(0.5)
