"""Adaptive Solar integration; importing the offline core never imports HA."""
from __future__ import annotations


async def async_setup_entry(hass, entry) -> bool:
    """Set up one site from a UI config entry."""
    from homeassistant.const import Platform
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    from homeassistant.helpers.importlib import async_import_module

    from .const import CONF_SITE
    from .core.models import SiteConfig
    from .weather import OpenMeteoClient

    coordinator_module = await async_import_module(hass, f"{__package__}.coordinator")
    config = SiteConfig.from_dict(entry.options.get(CONF_SITE, entry.data[CONF_SITE]))
    coordinator = coordinator_module.AdaptiveSolarCoordinator(hass, entry, config, OpenMeteoClient(async_get_clientsession(hass), config))
    try:
        services_module = await async_import_module(hass, f"{__package__}.services")
        await coordinator.async_restore()
        await coordinator.async_config_entry_first_refresh()
        entry.runtime_data = coordinator
        coordinator.async_start_tracking()
        await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])
    except BaseException:
        await coordinator.async_close()
        raise
    entry.async_on_unload(entry.add_update_listener(_async_update_options))
    services_module.async_register_reference_service(hass, entry.entry_id)
    coordinator.async_commit_setup()
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
