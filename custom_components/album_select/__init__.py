"""Integration for selecting random albums for picture frames."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.discovery import async_load_platform

DOMAIN = "album_select"
PLATFORMS = [Platform.SENSOR]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the album_select integration from YAML."""
    if DOMAIN in config:
        # Forward the configuration to the sensor platform
        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN]["config"] = config[DOMAIN]
        await async_load_platform(hass, "sensor", DOMAIN, {}, config)

    # Register the select_album service
    async def select_new_album(call: ServiceCall) -> None:
        """Service to select a new album."""
        # Find the sensor entity
        entity_id = f"sensor.{DOMAIN}"
        entity = hass.states.get(entity_id)
        
        if entity is None:
            return
            
        # Get the sensor object to call its update method
        for component in hass.data.get("sensor", {}).get("entities", []):
            if component.entity_id == entity_id and hasattr(component, "async_update_album"):
                await component.async_update_album()
                break

    hass.services.async_register(DOMAIN, "select_next_album", select_new_album)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up album_select from a config entry."""
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
