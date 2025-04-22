"""Integration for selecting random albums for picture frames."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

DOMAIN = "album_select"
PLATFORMS = [Platform.SENSOR]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the album_select integration from YAML."""
    if DOMAIN in config:
        # Forward the configuration to the sensor platform
        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN]["config"] = config[DOMAIN]
        await hass.helpers.discovery.async_load_platform("sensor", DOMAIN, {}, config)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up album_select from a config entry."""
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
