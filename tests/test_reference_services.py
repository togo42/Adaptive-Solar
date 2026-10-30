"""Real HA response-only service with mocked native Energy provider reads."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import HomeAssistantError
import probatio as vol

from custom_components.adaptive_solar import services

T = datetime(2026, 10, 25, 0, tzinfo=timezone.utc)
WH = {"wh_hours": {"2026-10-25T02:00:00+02:00": 100.25, "2026-10-25T02:00:00+01:00": 200.75}}


def entry(domain="helios_forecast", state=ConfigEntryState.LOADED):
    return SimpleNamespace(domain=domain, state=state)


async def call(hass, ids):
    return await hass.services.async_call("adaptive_solar", services.SERVICE,
        {"config_entry_ids": ids}, blocking=True, return_response=True)


async def test_bridge_returns_exact_native_wh_without_energy_preferences_or_refresh(hass):
    native = AsyncMock(return_value=WH)
    services.async_register_reference_service(hass, "owner")
    before = datetime.now(timezone.utc)
    with patch.object(hass.config_entries, "async_get_entry", return_value=entry()), patch.object(
            services, "async_get_energy_platforms", new=AsyncMock(return_value={"helios_forecast": native})):
        result = await call(hass, ["private-entry"])
    after = datetime.now(timezone.utc)
    assert result["private-entry"]["forecast"] == WH
    assert result["private-entry"]["forecast"] is not WH
    assert result["private-entry"]["status"] == "available"
    assert before <= datetime.fromisoformat(result["private-entry"]["retrieved_at"]) <= after
    native.assert_awaited_once_with(hass, "private-entry")
    assert hass.services.supports_response("adaptive_solar", services.SERVICE) is SupportsResponse.ONLY


@pytest.mark.parametrize("offset", [0, 330, 345, -210, 570, .5])
async def test_reference_bridge_checks_absolute_utc_hour_and_preserves_offset_representation(hass, offset):
    stamp = T.astimezone(timezone(timedelta(minutes=offset))).isoformat()
    raw = {"wh_hours": {stamp: 100.25}}
    services.async_register_reference_service(hass, "owner")
    with patch.object(hass.config_entries, "async_get_entry", return_value=entry()), patch.object(
            services, "async_get_energy_platforms", new=AsyncMock(return_value={"helios_forecast": AsyncMock(return_value=raw)})):
        result = await call(hass, ["private-entry"])
    assert result["private-entry"]["status"] == "available"
    assert result["private-entry"]["forecast"] == raw
    assert result["private-entry"]["forecast"] is not raw


@pytest.mark.parametrize("offset", [330, 345, -210, 570, .5])
def test_reference_validator_rejects_local_whole_hour_off_the_utc_grid(offset):
    stamp = datetime(2026, 6, 1, 15, tzinfo=timezone(timedelta(minutes=offset))).isoformat()
    assert services._validated_forecast({"wh_hours": {stamp: 100}}) is None


def test_reference_validator_rejects_duplicate_absolute_hour_in_different_offsets():
    assert services._validated_forecast({"wh_hours": {
        T.isoformat(): 100, T.astimezone(timezone(timedelta(minutes=345))).isoformat(): 200}}) is None


@pytest.mark.parametrize("configured,status", [(None, "not_found"),
    (entry("other_integration"), "unsupported_domain"),
    (entry(state=ConfigEntryState.NOT_LOADED), "not_loaded")])
async def test_bridge_never_reads_missing_unloaded_or_unapproved_entry(hass, configured, status):
    native = AsyncMock(return_value=WH)
    services.async_register_reference_service(hass, "owner")
    with patch.object(hass.config_entries, "async_get_entry", return_value=configured), patch.object(
            services, "async_get_energy_platforms", new=AsyncMock(return_value={"helios_forecast": native})):
        result = await call(hass, ["private-entry"])
    assert result["private-entry"]["status"] == status
    assert result["private-entry"]["forecast"] is None
    assert result["private-entry"]["retrieved_at"]
    native.assert_not_called()


@pytest.mark.parametrize("raw", [None, {"wh_hours": {"2026-01-01T00:00:00": 20}},
    {"wh_hours": {T.isoformat(): True}}, {"wh_hours": {T.isoformat(): float("nan")}},
    {"wh_hours": {T.isoformat(): -1}}, {"watts": {T.isoformat(): 100}}])
async def test_bridge_rejects_malformed_native_values_without_fabricated_energy(hass, raw):
    services.async_register_reference_service(hass, "owner")
    with patch.object(hass.config_entries, "async_get_entry", return_value=entry()), patch.object(
            services, "async_get_energy_platforms", new=AsyncMock(return_value={"helios_forecast": AsyncMock(return_value=raw)})):
        result = await call(hass, ["private-entry"])
    assert result["private-entry"]["status"] in {"unavailable", "invalid_forecast"}
    assert result["private-entry"]["forecast"] is None


async def test_bridge_timeout_and_provider_error_are_bounded_and_private(hass):
    async def slow(*args):
        await asyncio.sleep(10)
    services.async_register_reference_service(hass, "owner")
    for provider, expected in ((slow, "timeout"), (AsyncMock(side_effect=RuntimeError("SECRET_PRIVATE_URL")), "error")):
        with patch.object(hass.config_entries, "async_get_entry", return_value=entry()), patch.object(
                services, "async_get_energy_platforms", new=AsyncMock(return_value={"helios_forecast": provider})), patch.object(services, "PROVIDER_TIMEOUT", 0.01):
            result = await call(hass, ["private-entry"])
        assert result["private-entry"]["status"] == expected
        assert "SECRET" not in str(result)
        assert result["private-entry"]["retrieved_at"]


async def test_bridge_max_16_duplicate_reads_and_multi_entry_lifecycle(hass):
    native = AsyncMock(return_value=WH)
    services.async_register_reference_service(hass, "owner-a")
    services.async_register_reference_service(hass, "owner-b")
    with patch.object(hass.config_entries, "async_get_entry", return_value=entry("open_meteo_solar_forecast")), patch.object(
            services, "async_get_energy_platforms", new=AsyncMock(return_value={"open_meteo_solar_forecast": native})):
        await call(hass, ["private-entry", "private-entry"])
        native.assert_awaited_once()
        with pytest.raises((vol.Invalid, HomeAssistantError)):
            await call(hass, [f"entry-{i}" for i in range(17)])
    services.async_unregister_reference_service(hass, "owner-a")
    assert hass.services.has_service("adaptive_solar", services.SERVICE)
    services.async_unregister_reference_service(hass, "owner-b")
    assert not hass.services.has_service("adaptive_solar", services.SERVICE)


async def test_failed_final_close_still_releases_service_after_platforms_unload(hass):
    from custom_components.adaptive_solar import async_unload_entry
    services.async_register_reference_service(hass, "owner")
    configured = SimpleNamespace(entry_id="owner", runtime_data=SimpleNamespace(async_close=AsyncMock(side_effect=OSError("private storage failure"))))
    with patch.object(hass.config_entries, "async_unload_platforms", new=AsyncMock(return_value=True)):
        with pytest.raises(OSError):
            await async_unload_entry(hass, configured)
    assert not hass.services.has_service("adaptive_solar", services.SERVICE)


def test_service_yaml_selector_is_valid_for_real_ha_and_accepts_explicit_id_array():
    from pathlib import Path
    from homeassistant.helpers import selector
    from homeassistant.util.yaml import load_yaml
    document = load_yaml(str(Path(services.__file__).with_name("services.yaml")))
    field = document[services.SERVICE]["fields"]["config_entry_ids"]
    native_selector = selector.selector(field["selector"])
    ids = native_selector(["entry-one", "entry-two"])
    assert services._SCHEMA({"config_entry_ids": ids}) == {"config_entry_ids": ["entry-one", "entry-two"]}
