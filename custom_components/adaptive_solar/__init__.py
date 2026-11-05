# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Torsten Godau
"""Adaptive Solar integration; importing the offline core never imports HA."""
from __future__ import annotations

import logging

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry) -> bool:
    """Set up one site from a UI config entry."""
    from homeassistant.const import Platform
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    from homeassistant.helpers.importlib import async_import_module

    from .const import CONF_SITE
    from .core.models import SiteConfig
    runtime_module = await async_import_module(hass, f"{__package__}._runtime")
    await runtime_module.async_ensure_runtime(hass)
    weather_module = await async_import_module(hass, f"{__package__}.weather")

    coordinator_module = await async_import_module(hass, f"{__package__}.coordinator")
    config = SiteConfig.from_dict(entry.options.get(CONF_SITE, entry.data[CONF_SITE]))
    coordinator = coordinator_module.AdaptiveSolarCoordinator(hass, entry, config, weather_module.OpenMeteoClient(async_get_clientsession(hass), config))
    services_module = None
    forwarding_started = False
    remove_options_listener = None
    try:
        services_module = await async_import_module(hass, f"{__package__}.services")
        await coordinator.async_restore()
        await coordinator.async_config_entry_first_refresh()
        entry.runtime_data = coordinator
        coordinator.async_start_tracking()
        forwarding_started = True
        await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])
        services_module.async_register_reference_service(hass, entry.entry_id)
        remove_options_listener = entry.add_update_listener(_async_update_options)
        # The wrapper is idempotent: rollback and HA's failed-setup callbacks
        # can both release the same listener.
        def remove_listener():
            nonlocal remove_options_listener
            if remove_options_listener is not None:
                remove_options_listener()
                remove_options_listener = None

        entry.async_on_unload(remove_listener)
        coordinator.async_commit_setup(defer_writes=True)
    except BaseException:
        # Revoke a partially completed commit before yielding during rollback.
        # No initial writer may run while HA marks this entry SETUP_ERROR.
        coordinator.async_abort_setup()
        if remove_options_listener is not None:
            try:
                remove_listener()
            except BaseException:
                _LOGGER.exception("Error releasing options listener after failed Adaptive Solar setup")
        if forwarding_started:
            try:
                if not await hass.config_entries.async_unload_platforms(entry, [Platform.SENSOR]):
                    _LOGGER.error("Could not fully unload platforms after failed Adaptive Solar setup")
            except BaseException:
                _LOGGER.exception("Error unloading platforms after failed Adaptive Solar setup")
        try:
            await coordinator.async_close()
        except BaseException:
            _LOGGER.exception("Error closing coordinator after failed Adaptive Solar setup")
        if services_module is not None:
            try:
                services_module.async_unregister_reference_service(hass, entry.entry_id)
            except BaseException:
                _LOGGER.exception("Error releasing services after failed Adaptive Solar setup")
        raise
    return True


async def _async_update_options(hass, entry) -> None:
    """Reload after a UI configuration edit."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry) -> bool:
    """Unload entities and flush bounded training data."""
    from homeassistant.const import Platform

    if await hass.config_entries.async_unload_platforms(entry, [Platform.SENSOR]):
        from .services import async_unregister_reference_service

        try:
            await entry.runtime_data.async_close()
        finally:
            async_unregister_reference_service(hass, entry.entry_id)
        return True
    return False
