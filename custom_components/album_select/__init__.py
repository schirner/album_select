"""Integration for selecting random albums for picture frames."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.typing import ConfigType

from .const import BASE_SCHEMA, DOMAIN, SERVICE_SELECT_NEXT_ALBUM

# Must live in the component module: homeassistant.config only validates
# CONFIG_SCHEMA found on the integration's top-level module.
CONFIG_SCHEMA = vol.Schema({DOMAIN: vol.Schema(BASE_SCHEMA)}, extra=vol.ALLOW_EXTRA)

DATA_CONFIG = "config"
DATA_ENTITIES = "entities"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the album_select integration from YAML."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    domain_data.setdefault(DATA_ENTITIES, [])

    if DOMAIN in config:
        domain_data[DATA_CONFIG] = config[DOMAIN]
        await async_load_platform(hass, "sensor", DOMAIN, {}, config)

    async def select_next_album(call: ServiceCall) -> None:
        """Select a new album immediately."""
        for entity in domain_data[DATA_ENTITIES]:
            await entity.async_update_album()

    hass.services.async_register(DOMAIN, SERVICE_SELECT_NEXT_ALBUM, select_next_album)

    return True
