# Album Select for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)

Randomly rotates a photo album for display on a picture frame or wall panel.

Albums are discovered by browsing a Home Assistant **media source**, not the
filesystem. The same code therefore works against an [Immich](https://immich.app/)
instance, a local media directory, or any other media source whose children are
album-like containers — selected purely by configuration.

## Why media sources rather than files

The original version enumerated directories and handed the panel a signed path
to the original file. That does not survive a real phone library:

- Phone photos are HEIC, and Chromium has no HEIF decoder for `<img>`, so those
  files never render in the Home Assistant Companion WebView.
- 10-bit HEVC video stalls the WebView without firing an `error` event, so a
  slideshow parks on a white screen with nothing in the log.
- Some filenames (for example one containing `(1)`) are rejected when signed.

Immich serves JPEG thumbnails and H.264 transcodes addressed by UUID, with no
filename in the path, which sidesteps all three.

## Installation

### HACS

1. In HACS, add this repository as a custom repository with category
   **Integration**.
2. Install **Album Select** and restart Home Assistant.

### Manual

Copy `custom_components/album_select` into your Home Assistant
`custom_components` directory and restart.

## Configuration

```yaml
album_select:
  root: immich          # or a literal media-source:// URI
  interval: 30          # minutes between albums
  min_assets: 5         # skip albums with fewer assets than this
  require_pattern: false
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `root` | string | `immich` | Where to look for albums. The magic value `immich` discovers the Immich album node at runtime. Any other value is used verbatim as a media-source URI, e.g. `media-source://media_source/local/photos`. |
| `interval` | integer | `30` | Minutes between album changes. |
| `min_assets` | integer | `0` | Skip albums with fewer than this many assets, so the frame does not sit on a two-photo album. `0` disables the check and avoids a browse per candidate. |
| `require_pattern` | boolean | `false` | When true, only albums named `YYYY-MM-Name` (or `YYYY_MM_Name`) are eligible. |

### Why `root: immich` is not a URI

An Immich album URI embeds the Immich user id, as in
`media-source://immich/<user-id>|albums|<album-id>`. Hardcoding it would break
whenever the account behind the integration changes, so the album node is
located by browsing down from the media source root each time. Only loaded
Immich config entries are listed there, so an unavailable instance is skipped
automatically.

## Entities

| Entity | State |
|--------|-------|
| `sensor.album_select` | The media-source URI of the selected album, verbatim. |
| `sensor.album_select_name` | A human-readable label for that album. |

The second entity exists because WallPanel's `${entity:<id>}` placeholder
substitutes entity *state* only, never attributes.

### Attributes on `sensor.album_select`

- `title` — the album's title as the media source reports it
- `display_name` — `Name · MM/YYYY` when the title matches the naming pattern,
  otherwise the title unchanged
- `year`, `month`, `name` — present only when the title matches the pattern
- `asset_count` — present only when `min_assets` is greater than zero
- `error` — present instead of the above when selection failed; the state is
  then `unknown`

## Actions

`album_select.select_next_album` selects a new album immediately, without
waiting for the next interval.

## Use with WallPanel

```yaml
wallpanel:
  enabled: true
  image_url: "${entity:sensor.album_select}"
  image_info_template: "${entity:sensor.album_select_name}"
```

## Upgrading from 0.0.x

Breaking changes:

- `path`, `uri_prefix` and `media_prefix` are removed. Use `root` instead —
  either `immich` or a literal `media-source://` URI.
- The `folder` attribute is removed; it has no meaning without a filesystem
  path. Use `title`, `display_name` or `asset_count`.
- Albums no longer need to match `YYYY-MM-Name`. 0.0.x filtered on it
  implicitly; set `require_pattern: true` to keep that behaviour.

## Development

Unit tests run in Docker and need no Home Assistant instance:

```bash
docker build -f Dockerfile.test -t album-select-test .
docker run --rm -v "$PWD":/workspace album-select-test pytest -q
```

`requirements_test.txt` pins `pytest-homeassistant-custom-component` to a
release matching a specific Home Assistant version — keep it aligned with the
instance you are targeting (Settings → About).

### Development instance

`docker-compose.yml` brings up Home Assistant on port 8124, with this
repository's `custom_components` mounted read-only and `dev-media/` mounted as
the media directory:

```bash
docker compose up -d
docker compose logs -f homeassistant
```

`dev-media/` holds seeded albums that exercise the options: one ordinary
album, one below `min_assets`, one using the `YYYY-MM_Name` separator variant,
and one with no date prefix for `require_pattern`.

To test the Immich path, add the Immich integration through the UI at
<http://localhost:8124> — pointing at an existing Immich server with a
read-scoped API key is enough, no separate server is needed — then set
`root: immich` in `dev-config/configuration.yaml` and restart.

## License

MIT — see `LICENSE`.
