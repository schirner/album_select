# Album Select for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)

The Album Select integration for Home Assistant allows you to randomly select photo albums for display on picture frames or other display devices. It's particularly useful when you want to rotate through different photo albums at set intervals.

## Features

- Randomly selects photo albums from a specified directory
- Updates at configurable intervals
- Provides album metadata including year, month, name, and URI
- Works with albums that follow the naming pattern: `YYYY-MM-AlbumName` or `YYYY_MM_AlbumName`

## Installation

### HACS (Recommended)

1. Make sure [HACS](https://hacs.xyz/) is installed in your Home Assistant instance
2. Add this repository as a custom repository in HACS:
   - Go to HACS in your Home Assistant instance
   - Click on "Integrations"
   - Click the three dots in the top right corner and select "Custom repositories"
   - Add the URL of this repository and select "Integration" as the category
3. Click "Install" on the Album Select integration
4. Restart Home Assistant

### Manual Installation

1. Copy the `album_select` directory from this repository to your Home Assistant's `custom_components` directory
2. Restart Home Assistant

## Configuration

Add the following to your `configuration.yaml`:

```yaml
album_select:
  path: "/path/to/your/albums"  # Required: Directory containing album folders
  interval: 30                  # Optional: Update interval in minutes (default: 30)
  uri_prefix: "media-source://media_source/local"  # Optional: URI prefix for media access
  media_prefix: "/media"        # Optional: File system prefix to replace with uri_prefix
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `path` | string | `/media/rock2_photo/onedrive` | Path to the directory containing your photo albums |
| `interval` | integer | 30 | Time interval in minutes between album changes |
| `uri_prefix` | string | `media-source://media_source/local` | URI prefix used for media access in Home Assistant |
| `media_prefix` | string | `/media` | File system prefix to be replaced with uri_prefix |

## Usage

Once configured, the integration will create a sensor entity called `sensor.album_select` which will randomly select an album at the specified interval.

### Sensor Attributes

The sensor provides the following attributes:

- `year`: The year of the album (extracted from folder name)
- `month`: The month of the album (extracted from folder name)
- `name`: The name of the album (extracted from folder name)
- `uri`: The URI to access the album in Home Assistant
- `path`: The local file system path to the album

### Example Automations

You can use this sensor to automatically change the displayed album on a picture frame:

```yaml
automation:
  - alias: Update Picture Frame Album
    trigger:
      - platform: state
        entity_id: sensor.album_select
    action:
      - service: media_player.play_media
        target:
          entity_id: media_player.picture_frame
        data:
          media_content_id: "{{ state_attr('sensor.album_select', 'uri') }}"
          media_content_type: "image/jpeg"
```

## Troubleshooting

If the sensor shows no state or displays an error, check:
1. The path exists and is accessible by Home Assistant
2. The album folders follow the naming convention `YYYY-MM-AlbumName` or `YYYY_MM_AlbumName`
3. Home Assistant has proper permissions to read the specified directory

## License

This project is licensed under the MIT License - see the LICENSE file for details.