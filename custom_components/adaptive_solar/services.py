"""Response-only bridge to loaded reference providers' native Energy forecasts.

HA 2026.10.2/3 energy.websocket_api.async_get_energy_platforms is the same
read path used by energy/solar_forecast, without its Energy-preference filter.
No provider refresh, configuration write or point-power integration occurs.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import math

import probatio as vol
from homeassistant.components.energy.websocket_api import async_get_energy_platforms
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import SupportsResponse, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.exceptions import ServiceValidationError

from .const import DOMAIN

SERVICE = "get_reference_forecasts"
RESTORE_SERVICE = "restore_day_start_forecast"
EXPORT_SERVICE = "export_archive"


def _strict_int(value):
    if type(value) is not int:
        raise vol.Invalid("Expected an integer")
    return value


_EXPORT_SCHEMA = vol.Schema({
    vol.Required("config_entry_id"): cv.string,
    vol.Optional("cursor"): vol.Any(None, cv.string),
    vol.Optional("generation"): cv.string,
    vol.Optional("limit", default=100): vol.All(_strict_int, vol.Range(min=1, max=1000)),
    vol.Optional("max_bytes", default=2 * 1024 * 1024): vol.All(_strict_int, vol.Range(min=1024, max=4 * 1024 * 1024)),
})
_ALLOWED = {"helios_forecast", "open_meteo_solar_forecast"}
_OWNERS = f"{DOMAIN}_reference_service_owners"
PROVIDER_TIMEOUT = 5.0
_SCHEMA = vol.Schema({vol.Required("config_entry_ids"): vol.All(cv.ensure_list, [cv.string], vol.Length(min=1, max=16))})
_RESTORE_SCHEMA = vol.Schema({vol.Required("config_entry_id"): cv.string,
                              vol.Required("day"): cv.string,
                              vol.Required("snapshot"): dict,
                              vol.Required("source_site"): dict})


def _validated_forecast(value):
    if not isinstance(value, dict) or set(value) != {"wh_hours"} or not isinstance(value["wh_hours"], dict):
        return None
    normalized = set()
    for stamp, wh in value["wh_hours"].items():
        if not isinstance(stamp, str):
            return None
        try:
            parsed = datetime.fromisoformat(stamp)
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                return None
            instant = parsed.astimezone(timezone.utc)
            if instant.minute or instant.second or instant.microsecond:
                return None
        except (ValueError, TypeError, OverflowError):
            return None
        if instant in normalized or isinstance(wh, bool) or not isinstance(wh, (int, float)) or not math.isfinite(wh) or wh < 0:
            return None
        normalized.add(instant)
    return deepcopy(value)


async def _read_references(hass, call):
    ids = call.data["config_entry_ids"]
    # Duplicate requests must not create duplicate weighting or repeated reads.
    ids = list(dict.fromkeys(ids))
    try:
        async with asyncio.timeout(PROVIDER_TIMEOUT):
            platforms = await async_get_energy_platforms(hass)
    except Exception:
        platforms = {}

    async def read(entry_id):
        entry = hass.config_entries.async_get_entry(entry_id)
        domain = entry.domain if entry is not None else None
        status, forecast = "not_found", None
        received = None
        if entry is not None:
            if domain not in _ALLOWED:
                status = "unsupported_domain"
            elif entry.state is not ConfigEntryState.LOADED:
                status = "not_loaded"
            elif domain not in platforms:
                status = "unavailable"
            else:
                try:
                    async with asyncio.timeout(PROVIDER_TIMEOUT):
                        raw = await platforms[domain](hass, entry_id)
                        # Stamp immediately after the native response, before
                        # parsing/copying. An upstream failure is stamped too.
                        received = datetime.now(timezone.utc)
                        forecast = _validated_forecast(raw)
                    status = "available" if forecast is not None else "invalid_forecast"
                    if raw is None:
                        status = "unavailable"
                except TimeoutError:
                    status = "timeout"
                except Exception:
                    # Exception strings may contain private provider data.
                    status = "error"
        if received is None:
            received = datetime.now(timezone.utc)
        return entry_id, {"domain": domain, "status": status, "forecast": forecast,
                          "retrieved_at": received.isoformat()}

    return dict(await asyncio.gather(*(read(entry_id) for entry_id in ids)))


@callback
def async_register_reference_service(hass, owner_entry_id):
    """Register once; count only entries whose setup completed successfully."""
    owners = hass.data.setdefault(_OWNERS, set())
    owners.add(owner_entry_id)
    if not hass.services.has_service(DOMAIN, EXPORT_SERVICE):
        async def export_handler(call):
            entry = hass.config_entries.async_get_entry(call.data["config_entry_id"])
            if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
                raise ServiceValidationError("Select a loaded Adaptive Solar entry")
            cursor = call.data.get("cursor")
            generation = call.data.get("generation")
            if generation is not None:
                if cursor is None:
                    cursor = f"{generation}:0"
                elif not cursor.startswith(f"{generation}:"):
                    raise ServiceValidationError("Cursor and generation disagree")
            try:
                return await entry.runtime_data.export.page(cursor, call.data["limit"], call.data["max_bytes"])
            except ValueError as err:
                raise ServiceValidationError("Invalid archive export cursor or page request") from err

        async_register_admin_service(hass, DOMAIN, EXPORT_SERVICE, export_handler,
                                     schema=_EXPORT_SCHEMA, supports_response=SupportsResponse.ONLY)
    if not hass.services.has_service(DOMAIN, RESTORE_SERVICE):
        async def restore_handler(call):
            from .core.models import SiteConfig

            entry = hass.config_entries.async_get_entry(call.data["config_entry_id"])
            if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
                raise ServiceValidationError("Select a loaded Adaptive Solar entry")
            try:
                await entry.runtime_data.async_restore_day_start(call.data["day"], call.data["snapshot"],
                                                                SiteConfig.from_dict(call.data["source_site"]))
            except (KeyError, TypeError, ValueError, OverflowError) as err:
                raise ServiceValidationError("Invalid or incompatible original day-start forecast") from err

        async_register_admin_service(hass, DOMAIN, RESTORE_SERVICE, restore_handler, schema=_RESTORE_SCHEMA)
    if hass.services.has_service(DOMAIN, SERVICE):
        return

    async def handler(call):
        return await _read_references(hass, call)

    hass.services.async_register(DOMAIN, SERVICE, handler, schema=_SCHEMA, supports_response=SupportsResponse.ONLY)


@callback
def async_unregister_reference_service(hass, owner_entry_id):
    """The last successfully unloaded Adaptive entry releases the service."""
    owners = hass.data.get(_OWNERS, set())
    owners.discard(owner_entry_id)
    if owners:
        return
    hass.services.async_remove(DOMAIN, SERVICE)
    hass.services.async_remove(DOMAIN, RESTORE_SERVICE)
    hass.services.async_remove(DOMAIN, EXPORT_SERVICE)
    hass.data.pop(_OWNERS, None)
