"""Tests for album_select media-source traversal and album selection."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from homeassistant.components.media_source.error import Unresolvable
from homeassistant.const import MAX_LENGTH_STATE_STATE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.album_select.const import MAX_SELECTION_ATTEMPTS, MAX_STATE_LENGTH
from custom_components.album_select.sensor import (
    AlbumNameSensor,
    AlbumSelectSensor,
    async_resolve_root,
)

IMMICH_ROOT = "media-source://immich"
USER = "8c9ebcb0-b2d5-4bbf-b53c-212f2eca420d"
INSTANCE = f"{IMMICH_ROOT}/{USER}"
ALBUMS = f"{INSTANCE}|albums"


def node(title, uri, can_expand=True, children=None):
    """Build a stand-in for BrowseMediaSource."""
    return SimpleNamespace(
        title=title,
        media_content_id=uri,
        can_expand=can_expand,
        children=children or [],
    )


def album(name, count=0, uri=None):
    """Build an album node holding `count` non-expandable assets."""
    uri = uri or f"{ALBUMS}|{name}"
    return node(
        name,
        uri,
        children=[node(f"{i}.jpg", f"{uri}|{i}", can_expand=False) for i in range(count)],
    )


class Browser:
    """Fake media_source.async_browse_media backed by a URI -> node map."""

    def __init__(self, tree, errors=None):
        self.tree = tree
        self.errors = errors or {}
        self.calls = []

    async def __call__(self, hass, uri, **kwargs):
        self.calls.append(uri)
        if uri in self.errors:
            raise self.errors[uri]
        if uri not in self.tree:
            raise Unresolvable(f"unknown {uri}")
        return self.tree[uri]

    def count(self, uri):
        """Return how many times `uri` was browsed."""
        return self.calls.count(uri)


def immich_tree(albums):
    """Build a full Immich tree: root -> instance -> albums -> album nodes."""
    return {
        IMMICH_ROOT: node("Immich", IMMICH_ROOT, children=[node("Server", INSTANCE)]),
        INSTANCE: node(
            "Server",
            INSTANCE,
            children=[
                node("albums", ALBUMS),
                node("people", f"{INSTANCE}|people"),
            ],
        ),
        ALBUMS: node("albums", ALBUMS, children=albums),
        **{a.media_content_id: a for a in albums},
    }


_CREATED: list[AlbumSelectSensor] = []


def make_sensor(hass, browser, **kwargs):
    """Create a sensor wired to `hass`, with media_source browsing faked."""
    sensor = AlbumSelectSensor(root=kwargs.pop("root", "immich"), **kwargs)
    sensor.hass = hass
    _CREATED.append(sensor)
    return sensor


@pytest.fixture(autouse=True)
def _cancel_pending_rotations():
    """Every selection arms a rotation timer; drop it at teardown."""
    yield
    for sensor in _CREATED:
        sensor._handle_remove()
    _CREATED.clear()


def patch_choice_first():
    """Make selection deterministic: always take the first candidate."""
    return patch(
        "custom_components.album_select.sensor.random.choice", new=lambda seq: seq[0]
    )


def patch_browse(browser):
    """Patch the module attribute the sensor actually calls."""
    return patch(
        "custom_components.album_select.sensor.media_source.async_browse_media",
        new=browser,
    )


# --------------------------------------------------------------------------
# Root resolution
# --------------------------------------------------------------------------


async def test_resolves_immich_albums_node(hass: HomeAssistant) -> None:
    """A loaded Immich instance resolves to its |albums node."""
    browser = Browser(immich_tree([album("2026-08-UK", 3)]))
    with patch_browse(browser):
        assert await async_resolve_root(hass, "immich") == ALBUMS


async def test_no_immich_instance(hass: HomeAssistant) -> None:
    """Browsing the Immich root failing yields no root, not an exception."""
    browser = Browser({}, errors={IMMICH_ROOT: Unresolvable("not configured")})
    with patch_browse(browser):
        assert await async_resolve_root(hass, "immich") is None


async def test_immich_root_without_children(hass: HomeAssistant) -> None:
    """No loaded entries means no instance children, so no root.

    The Immich media source lists only loaded config entries, so an unloaded
    entry never appears here. There is deliberately no ConfigEntryState check.
    """
    browser = Browser({IMMICH_ROOT: node("Immich", IMMICH_ROOT, children=[])})
    with patch_browse(browser):
        assert await async_resolve_root(hass, "immich") is None


async def test_first_usable_instance_wins(hass: HomeAssistant) -> None:
    """With two instances, the first one exposing an albums node is used."""
    other = f"{IMMICH_ROOT}/other-user"
    tree = immich_tree([album("2026-08-UK", 3)])
    tree[IMMICH_ROOT] = node(
        "Immich", IMMICH_ROOT, children=[node("Other", other), node("Server", INSTANCE)]
    )
    tree[other] = node("Other", other, children=[node("people", f"{other}|people")])
    browser = Browser(tree)
    with patch_browse(browser):
        assert await async_resolve_root(hass, "immich") == ALBUMS


async def test_literal_root_is_untouched(hass: HomeAssistant) -> None:
    """A literal URI is returned verbatim with no config-entry lookup."""
    browser = Browser({})
    with patch_browse(browser):
        result = await async_resolve_root(hass, "media-source://media_source/local/x")
    assert result == "media-source://media_source/local/x"
    assert browser.calls == []


async def test_instance_browse_failure_is_skipped(hass: HomeAssistant) -> None:
    """An instance that cannot be browsed does not abort resolution."""
    tree = immich_tree([album("2026-08-UK", 3)])
    browser = Browser(tree, errors={INSTANCE: HomeAssistantError("boom")})
    with patch_browse(browser):
        assert await async_resolve_root(hass, "immich") is None


# --------------------------------------------------------------------------
# Album listing
# --------------------------------------------------------------------------


async def test_only_expandable_children_are_albums(hass: HomeAssistant) -> None:
    """Assets sitting alongside albums are not selectable."""
    albums = [album("2026-08-UK", 2)]
    tree = immich_tree(albums)
    tree[ALBUMS].children = [*albums, node("stray.jpg", f"{ALBUMS}|stray", can_expand=False)]
    browser = Browser(tree)
    sensor = make_sensor(hass, browser)
    with patch_browse(browser):
        found = await sensor._async_list_albums(ALBUMS)
    assert [a.title for a in found] == ["2026-08-UK"]


@pytest.mark.parametrize(
    ("require_pattern", "expected"),
    [(True, ["2026-08-UK"]), (False, ["2026-08-UK", "Misc"])],
    ids=["require_pattern_filters", "require_pattern_off_keeps_all"],
)
async def test_require_pattern(
    hass: HomeAssistant, require_pattern: bool, expected: list[str]
) -> None:
    """require_pattern decides whether unnamed albums survive."""
    albums = [album("2026-08-UK", 2), album("Misc", 2)]
    browser = Browser(immich_tree(albums))
    sensor = make_sensor(hass, browser, require_pattern=require_pattern)
    with patch_browse(browser):
        found = await sensor._async_list_albums(ALBUMS)
    assert [a.title for a in found] == expected


async def test_no_albums_sets_error(hass: HomeAssistant) -> None:
    """An empty library is an error state, not a crash."""
    browser = Browser(immich_tree([]))
    sensor = make_sensor(hass, browser)
    with patch_browse(browser):
        await sensor.async_update_album()
    assert sensor.state is None
    assert "error" in sensor.extra_state_attributes


# --------------------------------------------------------------------------
# Selection
# --------------------------------------------------------------------------


async def test_attributes_from_pattern(hass: HomeAssistant) -> None:
    """A conventionally named album yields year, month and name."""
    browser = Browser(immich_tree([album("2026-08-UK", 3)]))
    sensor = make_sensor(hass, browser)
    with patch_browse(browser):
        await sensor.async_update_album()
    attrs = sensor.extra_state_attributes
    assert attrs["year"] == "2026"
    assert attrs["month"] == "08"
    assert attrs["name"] == "UK"
    assert "UK" in attrs["display_name"]
    assert "2026" in attrs["display_name"]


@pytest.mark.parametrize(
    ("title", "year", "month", "name"),
    [
        ("2026-08-UK", "2026", "08", "UK"),
        ("2026-06_Croft", "2026", "06", "Croft"),
        ("2026_07_MollidgewockSP", "2026", "07", "MollidgewockSP"),
    ],
    ids=["dash", "mixed_separators", "underscores"],
)
async def test_separator_variants(
    hass: HomeAssistant, title: str, year: str, month: str, name: str
) -> None:
    """Both separators occur in the real library, sometimes mixed."""
    browser = Browser(immich_tree([album(title, 3)]))
    sensor = make_sensor(hass, browser)
    with patch_browse(browser):
        await sensor.async_update_album()
    attrs = sensor.extra_state_attributes
    assert (attrs["year"], attrs["month"], attrs["name"]) == (year, month, name)


async def test_attributes_without_pattern(hass: HomeAssistant) -> None:
    """An unconventional title falls back to itself and omits the parts."""
    browser = Browser(immich_tree([album("Misc", 3)]))
    sensor = make_sensor(hass, browser)
    with patch_browse(browser):
        await sensor.async_update_album()
    attrs = sensor.extra_state_attributes
    assert attrs["display_name"] == "Misc"
    assert "year" not in attrs
    assert "month" not in attrs
    assert "name" not in attrs


async def test_state_is_uri_verbatim(hass: HomeAssistant) -> None:
    """The state is exactly the media_content_id, with nothing added."""
    picked = album("2026-08-UK", 3)
    browser = Browser(immich_tree([picked]))
    sensor = make_sensor(hass, browser)
    with patch_browse(browser):
        await sensor.async_update_album()
    assert sensor.state == picked.media_content_id


async def test_avoids_immediate_repeat(hass: HomeAssistant) -> None:
    """Two albums must alternate rather than possibly repeat."""
    browser = Browser(immich_tree([album("2026-08-UK", 3), album("2026-09-DE", 3)]))
    sensor = make_sensor(hass, browser)
    # Without repeat avoidance a first-candidate pick would return the same
    # album twice, so this fails deterministically rather than one time in two.
    with patch_browse(browser), patch_choice_first():
        await sensor.async_update_album()
        first = sensor.state
        await sensor.async_update_album()
    assert sensor.state != first


async def test_single_album_can_repeat(hass: HomeAssistant) -> None:
    """Repeat avoidance must not deadlock a one-album library."""
    only = album("2026-08-UK", 3)
    browser = Browser(immich_tree([only]))
    sensor = make_sensor(hass, browser)
    with patch_browse(browser):
        await sensor.async_update_album()
        await sensor.async_update_album()
    assert sensor.state == only.media_content_id


async def test_state_cap_matches_home_assistant(hass: HomeAssistant) -> None:
    """Our guard must track the real HA limit, not drift from it."""
    assert MAX_STATE_LENGTH == MAX_LENGTH_STATE_STATE


async def test_overlong_uri_is_rejected(hass: HomeAssistant) -> None:
    """A URI beyond the HA state cap clears the state instead of truncating."""
    long_uri = "x" * (MAX_LENGTH_STATE_STATE + 1)
    browser = Browser(immich_tree([album("2026-08-UK", 3, uri=long_uri)]))
    sensor = make_sensor(hass, browser)
    with patch_browse(browser):
        await sensor.async_update_album()
    assert sensor.state is None
    assert "error" in sensor.extra_state_attributes


# --------------------------------------------------------------------------
# min_assets
# --------------------------------------------------------------------------


async def test_min_assets_zero_skips_counting(hass: HomeAssistant) -> None:
    """With both count consumers disabled, albums are never browsed."""
    picked = album("2026-08-UK", 3)
    browser = Browser(immich_tree([picked]))
    sensor = make_sensor(hass, browser, min_assets=0, display_time=0)
    with patch_browse(browser):
        await sensor.async_update_album()
    assert browser.count(picked.media_content_id) == 0
    assert "asset_count" not in sensor.extra_state_attributes


async def test_min_assets_rejects_small_album(hass: HomeAssistant) -> None:
    """A too-small album is passed over for a large one."""
    small = album("2026-08-UK", 2)
    large = album("2026-09-DE", 10)
    browser = Browser(immich_tree([small, large]))
    sensor = make_sensor(hass, browser, min_assets=5)
    with patch_browse(browser):
        await sensor.async_update_album()
    assert sensor.state == large.media_content_id
    assert sensor.extra_state_attributes["asset_count"] == 10


async def test_min_assets_gives_up_within_cap(hass: HomeAssistant) -> None:
    """When nothing qualifies, selection stops inside the attempt cap."""
    # A fixed library comfortably larger than any sane cap, so giving up proves
    # the cap fired rather than the candidate list simply running dry.
    albums = [album(f"2026-{i:02d}-A", 1) for i in range(1, 21)]
    browser = Browser(immich_tree(albums))
    sensor = make_sensor(hass, browser, min_assets=5)
    with patch_browse(browser):
        await sensor.async_update_album()
    assert sensor.state is None
    assert "error" in sensor.extra_state_attributes
    per_album = sum(browser.count(a.media_content_id) for a in albums)
    assert per_album <= MAX_SELECTION_ATTEMPTS
    assert per_album < len(albums)


async def test_asset_count_excludes_containers(hass: HomeAssistant) -> None:
    """Sub-containers inside an album do not count towards min_assets."""
    picked = album("2026-08-UK", 6)
    picked.children.append(node("subdir", f"{picked.media_content_id}|sub"))
    browser = Browser(immich_tree([picked]))
    sensor = make_sensor(hass, browser, min_assets=1)
    with patch_browse(browser):
        await sensor.async_update_album()
    assert sensor.extra_state_attributes["asset_count"] == 6


# --------------------------------------------------------------------------
# Regression: stale state
# --------------------------------------------------------------------------


async def test_failure_clears_previous_album(hass: HomeAssistant) -> None:
    """A later failure must not leave the previous album on display."""
    picked = album("2026-08-UK", 3)
    browser = Browser(immich_tree([picked]))
    sensor = make_sensor(hass, browser)
    with patch_browse(browser):
        await sensor.async_update_album()
        assert sensor.state == picked.media_content_id

        failing = Browser(immich_tree([picked]), errors={ALBUMS: HomeAssistantError("gone")})
    with patch_browse(failing):
        await sensor.async_update_album()
    assert sensor.state is None
    assert "error" in sensor.extra_state_attributes


# --------------------------------------------------------------------------
# Name entity
# --------------------------------------------------------------------------


async def test_name_sensor_tracks_display_name(hass: HomeAssistant) -> None:
    """The name entity mirrors the selected album's label."""
    browser = Browser(immich_tree([album("2026-08-UK", 3)]))
    sensor = make_sensor(hass, browser)
    name = AlbumNameSensor(sensor)
    with patch_browse(browser):
        await sensor.async_update_album()
    assert name.state == sensor.extra_state_attributes["display_name"]


async def test_name_sensor_updates_on_next_selection(hass: HomeAssistant) -> None:
    """The listener fires on each selection, without a restart."""
    browser = Browser(immich_tree([album("2026-08-UK", 3), album("2026-09-DE", 3)]))
    sensor = make_sensor(hass, browser)
    name = AlbumNameSensor(sensor)
    fired = []
    sensor.async_add_change_listener(lambda: fired.append(name.state))
    with patch_browse(browser):
        await sensor.async_update_album()
        await sensor.async_update_album()
    assert len(fired) == 2
    assert fired[0] != fired[1]


# --------------------------------------------------------------------------
# Hold time
# --------------------------------------------------------------------------


async def test_counts_assets_for_hold_time_alone(hass: HomeAssistant) -> None:
    """display_time needs the count even when min_assets does not."""
    picked = album("2026-08-UK", 3)
    browser = Browser(immich_tree([picked]))
    sensor = make_sensor(hass, browser, min_assets=0, display_time=15)
    with patch_browse(browser):
        await sensor.async_update_album()
    assert browser.count(picked.media_content_id) == 1
    assert sensor.extra_state_attributes["asset_count"] == 3


@pytest.mark.parametrize(
    ("count", "display_time", "interval", "expected"),
    [
        (12, 15, 30, 180.0),
        (4, 15, 30, 60.0),
        (1000, 15, 30, 1800.0),
        (12, 0, 30, 1800.0),
    ],
    ids=["short_album", "tiny_album", "capped_by_interval", "display_time_disabled"],
)
async def test_hold_seconds(
    hass: HomeAssistant, count: int, display_time: float, interval: int, expected: float
) -> None:
    """An album is held for its own length, bounded by the interval."""
    picked = album("2026-08-UK", count)
    browser = Browser(immich_tree([picked]))
    sensor = make_sensor(
        hass, browser, interval=interval, display_time=display_time, min_assets=0
    )
    with patch_browse(browser):
        await sensor.async_update_album()
    assert sensor.hold_seconds() == expected


async def test_failed_selection_holds_for_interval(hass: HomeAssistant) -> None:
    """With no album there is no count, so fall back to the interval."""
    browser = Browser(immich_tree([]))
    sensor = make_sensor(hass, browser, interval=30, display_time=15)
    with patch_browse(browser):
        await sensor.async_update_album()
    assert sensor.state is None
    assert sensor.hold_seconds() == 1800.0


async def test_rotation_is_rescheduled_not_stacked(hass: HomeAssistant) -> None:
    """Each selection replaces the pending rotation rather than adding one."""
    browser = Browser(immich_tree([album("2026-08-UK", 3), album("2026-09-DE", 3)]))
    sensor = make_sensor(hass, browser)
    unsubs = [MagicMock(name="unsub0"), MagicMock(name="unsub1")]
    with (
        patch_browse(browser),
        patch(
            "custom_components.album_select.sensor.async_call_later",
            side_effect=unsubs,
        ) as call_later,
    ):
        await sensor.async_update_album()
        await sensor.async_update_album()

    assert call_later.call_count == 2
    # The first timer was cancelled before the second was armed.
    unsubs[0].assert_called_once_with()
    unsubs[1].assert_not_called()


async def test_removal_stops_rotation(hass: HomeAssistant) -> None:
    """A selection finishing after removal must not arm a new timer."""
    browser = Browser(immich_tree([album("2026-08-UK", 3)]))
    sensor = make_sensor(hass, browser)
    sensor._handle_remove()
    with (
        patch_browse(browser),
        patch("custom_components.album_select.sensor.async_call_later") as call_later,
    ):
        await sensor.async_update_album()
    call_later.assert_not_called()
