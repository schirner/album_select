"""Sensor for selecting random albums for picture frames.

Albums are enumerated by browsing a Home Assistant media source rather than the
filesystem, so the same code path serves a local media directory, an Immich
instance, or any other media source whose children are album-like containers.
"""

from __future__ import annotations

import logging
import random
from typing import Any

from homeassistant.components import media_source
from homeassistant.components.sensor import (
    PLATFORM_SCHEMA as SENSOR_PLATFORM_SCHEMA,
    SensorEntity,
)
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import (
    ALBUM_REGEX,
    ALBUMS_SUFFIX,
    BASE_SCHEMA,
    CONF_DISPLAY_TIME,
    CONF_INTERVAL,
    CONF_MIN_ASSETS,
    CONF_REQUIRE_PATTERN,
    CONF_ROOT,
    DEFAULT_DISPLAY_TIME,
    DEFAULT_INTERVAL,
    DEFAULT_MIN_ASSETS,
    DEFAULT_REQUIRE_PATTERN,
    DEFAULT_ROOT,
    DOMAIN,
    MAX_SELECTION_ATTEMPTS,
    MAX_STATE_LENGTH,
    ROOT_IMMICH,
)

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = SENSOR_PLATFORM_SCHEMA.extend(BASE_SCHEMA)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType = None,
) -> None:
    """Set up the album select sensor platform."""
    if (
        discovery_info is not None
        and DOMAIN in hass.data
        and "config" in hass.data[DOMAIN]
    ):
        conf = hass.data[DOMAIN]["config"]
    else:
        conf = config

    sensor = AlbumSelectSensor(
        root=conf.get(CONF_ROOT, DEFAULT_ROOT),
        interval=conf.get(CONF_INTERVAL, DEFAULT_INTERVAL),
        require_pattern=conf.get(CONF_REQUIRE_PATTERN, DEFAULT_REQUIRE_PATTERN),
        min_assets=conf.get(CONF_MIN_ASSETS, DEFAULT_MIN_ASSETS),
        display_time=conf.get(CONF_DISPLAY_TIME, DEFAULT_DISPLAY_TIME),
    )
    hass.data.setdefault(DOMAIN, {}).setdefault("entities", []).append(sensor)
    async_add_entities([sensor, AlbumNameSensor(sensor)])


async def async_resolve_root(hass: HomeAssistant, root: str) -> str | None:
    """Resolve the configured root to a concrete media-source URI.

    Anything that is not ROOT_IMMICH is taken as a literal URI. For Immich the
    album node is found by browsing down from the media source root: its
    identifier embeds the Immich user id, which must never be reconstructed
    here. Browsing also filters to loaded config entries for free, since the
    Immich media source lists only those.
    """
    if root != ROOT_IMMICH:
        return root

    immich_root = media_source.generate_media_source_id(ROOT_IMMICH, "")
    instances = await _async_browse(hass, immich_root)
    if instances is None:
        return None

    for instance in instances.children or []:
        collections = await _async_browse(hass, str(instance.media_content_id))
        if collections is None:
            continue
        for child in collections.children or []:
            if str(child.media_content_id).endswith(ALBUMS_SUFFIX):
                return str(child.media_content_id)
        _LOGGER.debug("No albums node under %s", instance.media_content_id)

    _LOGGER.warning("No Immich albums node found; is the Immich integration loaded?")
    return None


async def _async_browse(hass: HomeAssistant, uri: str) -> Any | None:
    """Browse a media-source URI, returning None instead of raising."""
    try:
        return await media_source.async_browse_media(hass, uri)
    except (HomeAssistantError, ValueError) as ex:
        _LOGGER.debug("Could not browse %s: %s", uri, ex)
        return None


class AlbumSelectSensor(SensorEntity):
    """Selects a random album and exposes its media-source URI as state."""

    _attr_should_poll = False

    def __init__(
        self,
        root: str,
        interval: int = DEFAULT_INTERVAL,
        require_pattern: bool = DEFAULT_REQUIRE_PATTERN,
        min_assets: int = DEFAULT_MIN_ASSETS,
        display_time: float = DEFAULT_DISPLAY_TIME,
    ) -> None:
        """Initialize the album select sensor."""
        self._root = root
        self._interval = interval
        self._require_pattern = require_pattern
        self._min_assets = min_assets
        self._display_time = display_time
        self._unsub_timer: CALLBACK_TYPE | None = None
        self._removed = False
        self._state: str | None = None
        self._attrs: dict[str, Any] = {}
        self._last_uri: str | None = None
        self._listeners: list[CALLBACK_TYPE] = []
        self._attr_unique_id = "album_select"
        self._attr_name = "Album Select"

    async def async_added_to_hass(self) -> None:
        """Make the first selection once Home Assistant is started."""
        self.async_on_remove(self._handle_remove)
        self.async_on_remove(async_at_started(self.hass, self._async_first_update))

    async def _async_first_update(self, _hass: HomeAssistant) -> None:
        """Select once Home Assistant is started, so media sources are loaded."""
        await self.async_update_album()

    async def _async_scheduled_update(self, _now) -> None:
        """Handle the rotation timer."""
        await self.async_update_album()

    @callback
    def _handle_remove(self) -> None:
        """Stop rotating for good; a selection may still be in flight."""
        self._removed = True
        self._cancel_timer()

    @callback
    def _cancel_timer(self) -> None:
        """Cancel a pending rotation, if any."""
        if self._unsub_timer is not None:
            self._unsub_timer()
            self._unsub_timer = None

    @callback
    def hold_seconds(self) -> float:
        """Return how long the current album should stay on screen.

        An album runs out of new material after asset_count * display_time
        seconds, so holding it longer than that only repeats pictures. The
        configured interval remains the upper bound.
        """
        interval = self._interval * 60
        count = self._attrs.get("asset_count")
        if self._display_time <= 0 or not count:
            return float(interval)
        return float(min(interval, count * self._display_time))

    @callback
    def _schedule_next(self) -> None:
        """Queue the next rotation, replacing any pending one."""
        self._cancel_timer()
        if self.hass is None or self._removed:
            return
        delay = self.hold_seconds()
        _LOGGER.debug("Holding album for %.0f s", delay)
        self._unsub_timer = async_call_later(
            self.hass, delay, self._async_scheduled_update
        )

    @property
    def state(self) -> str | None:
        """Return the media-source URI of the selected album."""
        return self._state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return album metadata."""
        return self._attrs

    @property
    def display_name(self) -> str:
        """Return a human readable label for the selected album."""
        return self._attrs.get("display_name", "")

    @callback
    def async_add_change_listener(self, listener: CALLBACK_TYPE) -> None:
        """Register a callback fired after each selection attempt."""
        self._listeners.append(listener)

    @callback
    def _notify(self) -> None:
        """Write state and fan out to dependent entities."""
        if self.hass is not None and self.entity_id is not None:
            self.async_write_ha_state()
        for listener in self._listeners:
            listener()

    async def async_update_album(self) -> None:
        """Pick a new random album and queue the next rotation."""
        try:
            await self._async_select_album()
        finally:
            self._schedule_next()

    async def _async_select_album(self) -> None:
        """Pick a new random album."""
        root_uri = await async_resolve_root(self.hass, self._root)
        if root_uri is None:
            self._fail(f"Could not resolve album root {self._root!r}")
            return

        albums = await self._async_list_albums(root_uri)
        if not albums:
            self._fail(f"No albums found under {root_uri}")
            return

        # Avoid repeating the previous album when there is an alternative.
        candidates = [a for a in albums if a.media_content_id != self._last_uri]
        if not candidates:
            candidates = albums

        for _ in range(MAX_SELECTION_ATTEMPTS):
            album = random.choice(candidates)
            count = await self._async_asset_count(album)
            if count is None or count >= self._min_assets:
                self._select(album, count)
                return
            _LOGGER.debug(
                "Skipping %s: %s assets < min_assets %s",
                album.title,
                count,
                self._min_assets,
            )
            candidates = [a for a in candidates if a is not album]
            if not candidates:
                break

        self._fail(f"No album under {root_uri} satisfied min_assets")

    @callback
    def _select(self, album: Any, count: int | None) -> None:
        """Store the selected album as state and attributes."""
        uri = str(album.media_content_id)
        if len(uri) > MAX_STATE_LENGTH:
            self._fail(f"Album URI exceeds {MAX_STATE_LENGTH} characters: {len(uri)}")
            return

        title = album.title or ""
        attrs: dict[str, Any] = {"title": title, "display_name": title}

        if match := ALBUM_REGEX.match(title):
            year, month, name = match.groups()
            attrs.update(
                {
                    "year": year,
                    "month": month,
                    "name": name,
                    "display_name": f"{name} · {month}/{year}",
                }
            )

        if count is not None:
            attrs["asset_count"] = count

        self._state = uri
        self._last_uri = uri
        self._attrs = attrs
        self._notify()

    @callback
    def _fail(self, message: str) -> None:
        """Clear state and record why selection failed."""
        _LOGGER.warning("Album selection failed: %s", message)
        self._state = None
        self._attrs = {"error": message}
        self._notify()

    async def _async_list_albums(self, root_uri: str) -> list[Any]:
        """Browse the root node and return its album children."""
        listing = await _async_browse(self.hass, root_uri)
        if listing is None:
            return []

        albums = [
            child
            for child in (listing.children or [])
            if getattr(child, "can_expand", False)
        ]
        if self._require_pattern:
            albums = [a for a in albums if ALBUM_REGEX.match(a.title or "")]
        return albums

    async def _async_asset_count(self, album: Any) -> int | None:
        """Count the assets in an album, or None when nothing needs the count."""
        if self._min_assets <= 0 and self._display_time <= 0:
            return None
        listing = await _async_browse(self.hass, str(album.media_content_id))
        if listing is None:
            return None
        return len(
            [c for c in (listing.children or []) if not getattr(c, "can_expand", False)]
        )


class AlbumNameSensor(SensorEntity):
    """Exposes the selected album's display name as state.

    WallPanel's ${entity:<id>} placeholder substitutes entity state only, so a
    separate entity is needed to render the album label in image_info_template.
    """

    _attr_should_poll = False

    def __init__(self, source: AlbumSelectSensor) -> None:
        """Initialize the album name sensor."""
        self._source = source
        self._attr_unique_id = "album_select_name"
        self._attr_name = "Album Select Name"

    async def async_added_to_hass(self) -> None:
        """Subscribe to selection changes."""
        self._source.async_add_change_listener(self._handle_change)

    @callback
    def _handle_change(self) -> None:
        """Re-render when the source sensor selects a new album."""
        self.async_write_ha_state()

    @property
    def state(self) -> str:
        """Return the display name of the selected album."""
        return self._source.display_name
