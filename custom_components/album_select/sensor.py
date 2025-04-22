"""Sensor for selecting random albums for picture frames."""

from __future__ import annotations

import asyncio
import random
import re
from datetime import timedelta
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components.sensor import (
    PLATFORM_SCHEMA as SENSOR_PLATFORM_SCHEMA,
    SensorEntity,
)
from homeassistant.const import CONF_PATH
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
import homeassistant.helpers.config_validation as cv

DOMAIN = "album_select"

CONF_INTERVAL = "interval"
CONF_URI_PREFIX = "uri_prefix"
CONF_MEDIA_PREFIX = "media_prefix"

DEFAULT_PATH = "/media/rock2_photo/onedrive"
DEFAULT_INTERVAL = 30  # minutes
DEFAULT_URI_PREFIX = "media-source://media_source/local"
DEFAULT_MEDIA_PREFIX = "/media"

# Configuration schema for YAML configuration
CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional(CONF_PATH, default=DEFAULT_PATH): cv.string,
                vol.Optional(CONF_INTERVAL, default=DEFAULT_INTERVAL): cv.positive_int,
                vol.Optional(CONF_URI_PREFIX, default=DEFAULT_URI_PREFIX): cv.string,
                vol.Optional(
                    CONF_MEDIA_PREFIX, default=DEFAULT_MEDIA_PREFIX
                ): cv.string,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

# Platform schema for platform setup
PLATFORM_SCHEMA = SENSOR_PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_PATH, default=DEFAULT_PATH): cv.string,
        vol.Optional(CONF_INTERVAL, default=DEFAULT_INTERVAL): cv.positive_int,
        vol.Optional(CONF_URI_PREFIX, default=DEFAULT_URI_PREFIX): cv.string,
        vol.Optional(CONF_MEDIA_PREFIX, default=DEFAULT_MEDIA_PREFIX): cv.string,
    }
)

ALBUM_REGEX = re.compile(r"(\d{4})[-_](\d{2})[-_](.*)")


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType = None,
) -> None:
    """Set up the album select sensor platform."""
    # If discovery_info is provided, use the config from hass.data
    if (
        discovery_info is not None
        and DOMAIN in hass.data
        and "config" in hass.data[DOMAIN]
    ):
        conf = hass.data[DOMAIN]["config"]
    else:
        conf = config

    path = conf.get(CONF_PATH, DEFAULT_PATH)
    interval = conf.get(CONF_INTERVAL, DEFAULT_INTERVAL)
    uri_prefix = conf.get(CONF_URI_PREFIX, DEFAULT_URI_PREFIX)
    media_prefix = conf.get(CONF_MEDIA_PREFIX, DEFAULT_MEDIA_PREFIX)

    sensor = AlbumSelectSensor(path, uri_prefix, media_prefix)
    async_add_entities([sensor])

    async def update_album(now):
        """Update the album at interval."""
        await sensor.async_update_album()

    async_track_time_interval(hass, update_album, timedelta(minutes=interval))
    await sensor.async_update_album()


class AlbumSelectSensor(SensorEntity):
    """Sensor for selecting random albums."""

    def __init__(self, path: str, uri_prefix: str, media_prefix: str) -> None:
        """Initialize the album select sensor."""
        self._path = Path(path)
        self._uri_prefix = uri_prefix
        self._media_prefix = media_prefix
        self._state = None
        self._attrs: dict[str, Any] = {}
        self._attr_unique_id = "album_select"
        self._attr_name = "Album Select"

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return self._attr_name

    @property
    def state(self) -> str | None:
        """Return the state of the sensor."""
        return self._state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes of the sensor."""
        return self._attrs

    async def async_update_album(self) -> None:
        """Update the album selection."""
        try:
            # Run file system operations in a separate thread to avoid blocking the event loop
            folders = await self._get_folders()

            if not folders:
                self._state = None
                self._attrs = {}
                return

            folder = random.choice(folders)
            match = ALBUM_REGEX.match(folder)
            if match:
                year, month, name = match.groups()
                local_path = str(self._path / folder)
                # Replace only the first occurrence of the media_prefix
                if local_path.startswith(self._media_prefix):
                    uri = local_path.replace(self._media_prefix, self._uri_prefix, 1)
                else:
                    uri = local_path  # fallback, no replacement
                self._state = folder
                self._attrs = {
                    "year": year,
                    "month": month,
                    "name": name,
                    "uri": uri,
                    "path": local_path,
                }
        except (FileNotFoundError, PermissionError) as ex:
            self._state = None
            self._attrs = {"error": str(ex)}

    async def _get_folders(self) -> list[str]:
        """Get album folders from the filesystem in a non-blocking way."""
        path = Path(self._path)

        def _get_matching_folders() -> list[str]:
            """Get folders that match the album pattern."""
            try:
                return [
                    f.name
                    for f in path.iterdir()
                    if f.is_dir() and ALBUM_REGEX.match(f.name)
                ]
            except (FileNotFoundError, PermissionError):
                return []

        # Run the blocking operation in a thread pool
        return await asyncio.get_running_loop().run_in_executor(
            None, _get_matching_folders
        )
