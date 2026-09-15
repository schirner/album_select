"""Constants for the album_select integration."""

from __future__ import annotations

import re
from typing import Final

import voluptuous as vol

import homeassistant.helpers.config_validation as cv

DOMAIN: Final = "album_select"

CONF_ROOT: Final = "root"
CONF_INTERVAL: Final = "interval"
CONF_REQUIRE_PATTERN: Final = "require_pattern"
CONF_MIN_ASSETS: Final = "min_assets"
CONF_DISPLAY_TIME: Final = "display_time"

# Magic value for CONF_ROOT: the Immich album node is discovered by browsing,
# because its identifier embeds the Immich user id rather than a fixed name.
ROOT_IMMICH: Final = "immich"

# Immich exposes its collections as "<user_id>|albums", "<user_id>|people", ...
ALBUMS_SUFFIX: Final = "|albums"

DEFAULT_ROOT: Final = ROOT_IMMICH
DEFAULT_INTERVAL: Final = 30  # minutes
DEFAULT_REQUIRE_PATTERN: Final = False
DEFAULT_MIN_ASSETS: Final = 0
# Seconds per photo. Matches WallPanel's own display_time default, so the
# computed hold time lines up with what the panel actually does. 0 disables.
DEFAULT_DISPLAY_TIME: Final = 15.0

# homeassistant.const.MAX_LENGTH_STATE_STATE; duplicated to keep the guard
# explicit at the point of use.
MAX_STATE_LENGTH: Final = 255

# Upper bound on albums rejected by min_assets before giving up, so a library
# full of small albums cannot spin.
MAX_SELECTION_ATTEMPTS: Final = 5

SERVICE_SELECT_NEXT_ALBUM: Final = "select_next_album"

ALBUM_REGEX: Final = re.compile(r"(\d{4})[-_](\d{2})[-_](.*)")

BASE_SCHEMA: Final = {
    vol.Optional(CONF_ROOT, default=DEFAULT_ROOT): cv.string,
    vol.Optional(CONF_INTERVAL, default=DEFAULT_INTERVAL): cv.positive_int,
    vol.Optional(CONF_REQUIRE_PATTERN, default=DEFAULT_REQUIRE_PATTERN): cv.boolean,
    vol.Optional(CONF_MIN_ASSETS, default=DEFAULT_MIN_ASSETS): cv.positive_int,
    vol.Optional(CONF_DISPLAY_TIME, default=DEFAULT_DISPLAY_TIME): vol.All(
        vol.Coerce(float), vol.Range(min=0)
    ),
}
