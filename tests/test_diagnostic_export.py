"""Opt-in raw diagnostic thinning preserves native measurement semantics."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID

import pytest
from freezegun import freeze_time
from homeassistant.core import State
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_solar.coordinator import AdaptiveSolarCoordinator
from custom_components.adaptive_solar.core.models import InverterConfig, SiteConfig, StringConfig
from custom_components.adaptive_solar.diagnostic_export import (
    CONF_SOURCE_REPORT_PROFILE, FULL, MAX_TRACKED_ENTITIES, NIGHT_SPARSE,
    NightPlan, SourceReportPolicy, calculate_night_plan,
)

NOW = datetime(2026, 11, 2, 0, tzinfo=UTC)
POWER = {"power_i": "power"}


def payload(at, state="0", unit="W", **attributes):
    return {"entity_id": "sensor.power", "state": state, "last_reported": at,
            "attributes": {"unit_of_measurement": unit, **attributes}}


def sparse():
    policy = SourceReportPolicy(NIGHT_SPARSE)
    policy.prepare("2026-11-02", NightPlan(NOW, NOW + timedelta(days=1), ((NOW, NOW + timedelta(hours=6)),)))
    policy.marker_ready = True
    return policy


def test_default_full_and_unknown_profile_preserve_every_report():
    for profile in (FULL, "future-unknown-profile"):
        policy = SourceReportPolicy(profile)
        assert all(policy.keep(payload(NOW), POWER, NOW) for _ in range(3))
        assert policy.status()["skipped_reports_since_restart"] == 0


def test_sparse_requires_marker_and_emits_only_genuine_hourly_heartbeat():
    policy = sparse()
    assert policy.keep(payload(NOW), POWER, NOW)
    at = NOW + timedelta(seconds=3599)
    assert not policy.keep(payload(at), POWER, at)
    at += timedelta(seconds=1)
    assert policy.keep(payload(at), POWER, at)
    assert policy.skipped_reports == 1
    policy.marker_ready = False
    assert policy.keep(payload(at), POWER, at)
    assert "not_complete_report_cadence" in policy.marker()["detail"]


@pytest.mark.parametrize("role,unit", [("energy", "kWh"), ("control", "W"), ("validity", "W")])
def test_meter_control_and_shared_role_reports_never_thinned(role, unit):
    policy = sparse()
    for n in range(3):
        at = NOW + timedelta(seconds=n)
        assert policy.keep(payload(at, unit=unit), {**POWER, "critical": role}, at)
    assert policy.skipped_reports == 0


@pytest.mark.parametrize("state,unit,attrs", [("unavailable", "W", {}), ("unknown", "W", {}),
    ("nan", "W", {}), ("0", "invalid", {}), ("0", "W", {"restored": True}),
    ("0.2", "W", {}), ("-1", "W", {})])
def test_invalid_nonzero_and_recovery_reports_are_always_retained(state, unit, attrs):
    policy = sparse()
    assert policy.keep(payload(NOW), POWER, NOW)
    at = NOW + timedelta(seconds=1)
    assert policy.keep(payload(at, state, unit, **attrs), POWER, at)
    at += timedelta(seconds=1)
    assert policy.keep(payload(at), POWER, at)


def test_unchanged_weather_sparse_but_changes_units_and_state_class_retained():
    policy = sparse()
    roles = {"temperature": "temperature"}
    assert policy.keep(payload(NOW, "-2", "°C"), roles, NOW)
    at = NOW + timedelta(seconds=1)
    assert not policy.keep(payload(at, "-2", "°C"), roles, at)
    assert policy.keep(payload(at, "-1", "°C"), roles, at)
    assert policy.keep(payload(at, "-1", "K"), roles, at)
    assert policy.keep(payload(at, "-1", "K", state_class="measurement"), roles, at)


@pytest.mark.parametrize("state,unit", [("2", "kW/m²"), ("2", "kW/m2"), ("0.5", "kW/m2")])
def test_implausible_or_natively_unsupported_irradiance_reports_stay_full(state, unit):
    policy = sparse()
    for n in range(2):
        at = NOW + timedelta(seconds=n)
        assert policy.keep(payload(at, state, unit), {"irradiance": "irradiance"}, at)


def test_day_edges_expired_plan_restart_and_capacity_fail_open_to_full():
    policy = sparse()
    for at in (NOW + timedelta(hours=6), NOW + timedelta(days=1)):
        assert policy.keep(payload(at), POWER, at)
        assert policy.keep(payload(at), POWER, at)
    restarted = SourceReportPolicy(NIGHT_SPARSE)
    assert restarted.keep(payload(NOW), POWER, NOW)
    assert restarted.keep(payload(NOW), POWER, NOW)
    policy = sparse()
    for n in range(MAX_TRACKED_ENTITIES + 2):
        report = {**payload(NOW), "entity_id": f"sensor.p{n}"}
        assert policy.keep(report, POWER, NOW)
    assert policy.status()["tracked_entities"] == MAX_TRACKED_ENTITIES


@pytest.mark.parametrize("day,hours", [(datetime(2026, 3, 29, tzinfo=UTC), 23),
                                      (datetime(2026, 10, 25, tzinfo=UTC), 25)])
def test_real_spa_windows_respect_both_dst_days_and_protect_daylight(day, hours):
    site = SimpleNamespace(latitude=52, longitude=13, timezone="Europe/Berlin")
    plan = calculate_night_plan(site, day)
    assert (plan.end - plan.start).total_seconds() == hours * 3600
    policy = SourceReportPolicy(NIGHT_SPARSE)
    policy.prepare("test", plan)
    policy.marker_ready = True
    noon = day.replace(hour=12)
    assert policy.keep(payload(noon), POWER, noon)
    assert policy.keep(payload(noon), POWER, noon)
    assert plan.windows and all(plan.start <= a < b <= plan.end for a, b in plan.windows)


def test_polar_case_has_no_sampling_plan():
    assert calculate_night_plan(SimpleNamespace(latitude=89, longitude=13, timezone="UTC"), NOW) is None


def test_adjacent_polar_transition_cannot_mark_daylight_as_sparse_night():
    from custom_components.adaptive_solar.core.physics import solar_position

    site = SimpleNamespace(latitude=67, longitude=7.31, timezone="Etc/GMT+12")
    now = datetime(2026, 6, 3, tzinfo=UTC)
    assert solar_position(site, now.replace(hour=1, minute=50)).elevation_deg > 0
    # Civil June2 has a pair; a neighboring date has NaT. Never skip that hole.
    assert calculate_night_plan(site, now) is None


async def test_native_callbacks_reduce_only_raw_repeats_and_keep_zero_energy_intervals(hass):
    site = SiteConfig(52, 13, "UTC", (StringConfig("s", "i", 1, 30, 180),),
                      (InverterConfig("i", 1, power_entity_id="sensor.power", energy_entity_id="sensor.energy"),))
    measured = []
    for profile in (FULL, NIGHT_SPARSE):
        entry = MockConfigEntry(domain="adaptive_solar", data={"site": site.to_dict()},
            options={"archive_export": True, CONF_SOURCE_REPORT_PROFILE: profile})
        entry.add_to_hass(hass)
        with patch("custom_components.adaptive_solar.coordinator.uuid4", return_value=UUID(int=1)):
            coordinator = AdaptiveSolarCoordinator(hass, entry, site, SimpleNamespace())
            coordinator.export.report_policy = sparse() if profile == NIGHT_SPARSE else SourceReportPolicy()
            coordinator.export.record = Mock()
            coordinator._export_software = {"source_sha256": "a" * 64}
            with freeze_time(NOW):
                for n in range(2):
                    at = NOW + timedelta(seconds=10 * n)
                    for entity, value, unit in [("sensor.power", "0", "W"), ("sensor.energy", "1", "kWh")]:
                        state = State(entity, value, {"unit_of_measurement": unit}, last_updated=at)
                        event = SimpleNamespace(event_type="state_reported", time_fired=at,
                            data={"entity_id": entity, "new_state": state, "last_reported": at})
                        coordinator._async_state_reported(event)
        calls = coordinator.export.record.call_args_list
        assert sum(c.args[0] == "source_report" for c in calls) == (4 if profile == FULL else 3)
        qualified = [c.args[1] for c in calls if c.args[0] == "qualified_interval"]
        assert len(qualified) == 1 and qualified[0]["energy_kwh"] == 0
        measured.append((qualified, coordinator.intervals, coordinator.tracker.last_outcome))
    assert measured[0] == measured[1]


@pytest.mark.parametrize("failure", ["filter_exception", "overflow"])
async def test_raw_export_falls_back_to_full_after_filter_failure_or_queue_overflow(hass, failure):
    site = SiteConfig(52, 13, "UTC", (StringConfig("s", "i", 1, 30, 180),),
                      (InverterConfig("i", 1, power_entity_id="sensor.power"),))
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": site.to_dict()},
        options={"archive_export": True, CONF_SOURCE_REPORT_PROFILE: NIGHT_SPARSE})
    entry.add_to_hass(hass)
    coordinator = AdaptiveSolarCoordinator(hass, entry, site, SimpleNamespace())
    coordinator.export.report_policy = sparse()
    coordinator.export.record = Mock()
    if failure == "filter_exception":
        coordinator.export.report_policy.keep = Mock(side_effect=ValueError("optional filter failed"))
    else:
        coordinator.export._status["last_error"] = "pending_overflow"
    with freeze_time(NOW):
        for n in range(2):
            at = NOW + timedelta(seconds=n)
            state = State("sensor.power", "0", {"unit_of_measurement": "W"}, last_updated=at)
            coordinator._export_source_report(SimpleNamespace(event_type="state_reported",
                data={"entity_id": "sensor.power", "new_state": state, "last_reported": at}), at)
    assert coordinator.export.record.call_count == 2
    assert not coordinator.export.report_policy.marker_ready


async def test_window_failure_does_not_block_native_forecast_path_or_claim_sparse_readiness(hass):
    site = SiteConfig(52, 13, "UTC", (StringConfig("s", "i", 1, 30, 180),), (InverterConfig("i", 1),))
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": site.to_dict()},
        options={"archive_export": True, CONF_SOURCE_REPORT_PROFILE: NIGHT_SPARSE})
    entry.add_to_hass(hass)
    coordinator = AdaptiveSolarCoordinator(hass, entry, site, SimpleNamespace())
    coordinator.export.record = Mock()
    with patch.object(hass, "async_add_executor_job", AsyncMock(side_effect=ValueError("geometry unavailable"))):
        await coordinator._async_update_report_policy(NOW)
    assert not coordinator.export.report_policy.status()["ready"]
    assert coordinator.export.record.call_args.args[0] == "source_report_policy"
    assert coordinator.export.record.call_args.args[1]["fallback_full"] is True
    assert coordinator.export.report_policy.keep(payload(NOW), POWER, NOW)


@pytest.mark.parametrize("profile", [FULL, NIGHT_SPARSE])
async def test_spa_runs_only_once_per_local_day_in_executor_never_in_report_callback(hass, profile):
    from threading import get_ident

    site = SiteConfig(52, 13, "UTC", (StringConfig("s", "i", 1, 30, 180),),
                      (InverterConfig("i", 1, power_entity_id="sensor.power"),))
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": site.to_dict()},
        options={"archive_export": True, CONF_SOURCE_REPORT_PROFILE: profile})
    entry.add_to_hass(hass)
    coordinator = AdaptiveSolarCoordinator(hass, entry, site, SimpleNamespace())
    coordinator.export.record = Mock()
    calls = []
    loop_thread = get_ident()

    def in_worker(config, now):
        assert get_ident() != loop_thread
        calls.append(now)
        return calculate_night_plan(config, now)

    with patch("custom_components.adaptive_solar.coordinator.calculate_night_plan", new=in_worker):
        await coordinator._async_update_report_policy(NOW)
        await coordinator._async_update_report_policy(NOW + timedelta(minutes=1))
        before = len(calls)
        with freeze_time(NOW):
            for n in range(2):
                at = NOW + timedelta(seconds=n)
                state = State("sensor.power", "0", {"unit_of_measurement": "W"}, last_updated=at)
                coordinator._export_source_report(SimpleNamespace(event_type="state_reported",
                    data={"entity_id": "sensor.power", "new_state": state, "last_reported": at}), at)
        assert len(calls) == before == (1 if profile == NIGHT_SPARSE else 0)
        await coordinator._async_update_report_policy(NOW + timedelta(days=1))
        assert len(calls) == (2 if profile == NIGHT_SPARSE else 0)
