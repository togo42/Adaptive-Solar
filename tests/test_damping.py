"""Generic dawn/dusk corrections preserve stage limits and old configurations."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.data_entry_flow import FlowResultType

from custom_components.adaptive_solar.const import DOMAIN
from custom_components.adaptive_solar.core.models import InverterConfig, SiteConfig, StringConfig
from custom_components.adaptive_solar.core.physics import _daylight_windows, damping_factor, inverter_power, string_dc_power
from tests.test_config_flow import INV, SITE, STRING
from tests.test_physics import T, config, weather


@pytest.mark.parametrize("field", ["damping_morning", "damping_evening"])
@pytest.mark.parametrize("value", [-.1, 1.01, float("nan"), float("inf"), True])
def test_invalid_damping_is_rejected(field, value):
    with pytest.raises(ValueError):
        StringConfig("s", "i", 5, 30, 180, **{field: value})


def test_zero_defaults_keep_legacy_json_and_roundtrip_explicit_values():
    site = config()
    serialized = site.to_dict()
    assert not {"damping_morning", "damping_evening"}.intersection(serialized["strings"][0])
    zero = replace(site, strings=(replace(site.strings[0], damping_morning=0, damping_evening=0),))
    assert zero.to_dict() == serialized
    active = replace(site, strings=(replace(site.strings[0], damping_morning=.3, damping_evening=.6),))
    assert SiteConfig.from_dict(active.to_dict()) == active
    with patch("custom_components.adaptive_solar.core.physics._daylight_windows", side_effect=AssertionError("unused")):
        assert damping_factor(site, site.strings[0], T) == 1


def test_analytic_daylight_landmarks_and_night():
    site = config()
    string = replace(site.strings[0], damping_morning=.3, damping_evening=.6)
    rise, setting = T.replace(hour=4), T.replace(hour=20)
    with patch("custom_components.adaptive_solar.core.physics._daylight_windows", return_value=((rise, setting),)):
        expected = ((rise, .7), (rise + timedelta(hours=4), .85), (rise + timedelta(hours=8), 1),
                    (setting - timedelta(hours=4), .7), (setting, .4), (rise - timedelta(hours=1), 1))
        for at, value in expected:
            assert damping_factor(site, string, at) == pytest.approx(value)


@pytest.mark.parametrize("day", [datetime(2026, 3, 29, tzinfo=UTC), datetime(2026, 10, 25, tzinfo=UTC)])
@pytest.mark.parametrize("longitude,zone", [(13, "Europe/Berlin"), (179, "UTC"), (-179, "UTC")])
def test_real_solar_day_covers_dst_and_midnight_crossing(day, longitude, zone):
    site = replace(config(), latitude=0 if zone == "UTC" else 52, longitude=longitude, timezone=zone)
    string = replace(site.strings[0], damping_morning=.4, damping_evening=.6)
    rise, setting = _daylight_windows(site.latitude, site.longitude, zone, day.date())[1]
    assert timedelta(hours=6) < setting - rise < timedelta(hours=18)
    assert damping_factor(site, string, rise) == pytest.approx(.6)
    assert damping_factor(site, string, rise + (setting - rise) / 2) == pytest.approx(1)
    assert damping_factor(site, string, setting) == pytest.approx(.4)


@pytest.mark.parametrize("month", [6, 12])
def test_polar_days_have_neutral_damping_without_invented_sunrise(month):
    site = replace(config(), latitude=80, longitude=15, timezone="Arctic/Longyearbyen")
    string = replace(site.strings[0], damping_morning=.9, damping_evening=.9)
    at = datetime(2026, month, 21, 12, tzinfo=UTC)
    assert _daylight_windows(site.latitude, site.longitude, site.timezone, at.date()) == ()
    assert damping_factor(site, string, at) == 1


@pytest.mark.parametrize("kind", ["ac", "dc"])
@pytest.mark.parametrize("cap", [3, 10])
def test_per_string_damping_precedes_shared_stage_clipping(kind, cap):
    strings = (StringConfig("a", "i", 5, 30, 180, damping_morning=1), StringConfig("b", "i", 5, 30, 180))
    stage = InverterConfig("i", cap) if kind == "ac" else InverterConfig("i", output_type="dc", max_output_kw=cap)
    site = SiteConfig(52, 13, "Europe/Berlin", strings, (stage,))
    point = weather()
    midpoint = point.start + (point.end - point.start) / 2
    windows = ((midpoint - timedelta(hours=4), midpoint + timedelta(hours=12)),)
    with patch("custom_components.adaptive_solar.core.physics._daylight_windows", return_value=windows):
        raw_a = string_dc_power(site, replace(strings[0], damping_morning=0), point)
        raw_b = string_dc_power(site, strings[1], point)
        assert string_dc_power(site, strings[0], point) == pytest.approx(raw_a * .5)
        efficiency = stage.efficiency if kind == "ac" else 1
        assert inverter_power(site, point)["i"] == pytest.approx(min(cap * 1000, (raw_a * .5 + raw_b) * efficiency))


async def test_native_setup_exposes_and_saves_corrections(hass, enable_custom_integrations):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], SITE)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], INV)
    assert {"horizon", "damping_morning", "damping_evening"} <= {key.schema for key in result["data_schema"].schema}
    with patch("custom_components.adaptive_solar.async_setup_entry", new=AsyncMock(return_value=True)):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {**STRING, "damping_morning": .3, "damping_evening": .6})
        await hass.async_block_till_done()
    assert result["type"] == FlowResultType.CREATE_ENTRY
    saved = SiteConfig.from_dict(result["data"]["site"]).strings[0]
    assert (saved.damping_morning, saved.damping_evening) == (.3, .6)
    assert saved.horizon[0].beam_transmission == .3
