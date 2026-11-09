# RemArt Frame for Home Assistant

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=trapplab&repository=ha-remart&category=integration)

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![GitHub Release](https://img.shields.io/github/v/release/trapplab/ha-remart)](https://github.com/trapplab/ha-remart/releases)
[![Validate](https://github.com/trapplab/ha-remart/actions/workflows/validate.yml/badge.svg)](https://github.com/trapplab/ha-remart/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/github/license/trapplab/ha-remart)](LICENSE)

Show art on a Samsung Frame TV from Home Assistant:

- **Gallery**: browse public-domain artworks from nine museum sources and photos from Unsplash and Pixabay in the media browser and send one to the Frame with a click.
- **Drag & drop**: drop your own pictures onto the RemArt Frame card to show them on the TV.
- **On the Frame**: see the images stored on the TV, with the one currently shown first, and switch between them without uploading again.

Images are brought to 16:9 before upload, so the Frame never stretches them: letterboxed on black by default, or cropped to fill the screen.

## Requirements

- Home Assistant 2026.10 or newer
- A Samsung Frame TV (2018 or newer) on the same network

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=trapplab&repository=ha-remart&category=integration)

Click the button above, or add it by hand:

1. In Home Assistant open *HACS → ⋮ → Custom repositories*.
2. Enter `https://github.com/trapplab/ha-remart`, type *Integration*, and click *Add*.
3. Search for **RemArt Frame**, click *Download* and restart Home Assistant.

### Manual

Copy `custom_components/remart` from the [latest release](https://github.com/trapplab/ha-remart/releases/latest) into your `config/custom_components/` folder and restart Home Assistant.

### Setup

[![Open your Home Assistant instance and start setting up RemArt Frame.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=remart)

Click the button above, or go to *Settings → Devices & services → Add integration → RemArt Frame*. Enter the TV's IP address and **accept the prompt on the TV** with the remote within 30 seconds.

## Gallery

Open *Media* in the sidebar, pick the Frame as the target player (bottom right), then *RemArt → a source → an artwork*. The image appears on the Frame in art mode.

| Source | API key |
| --- | --- |
| Art Institute of Chicago, The Met (European Paintings), Cleveland Museum of Art, SMK, Minneapolis Institute of Art, Wikimedia Commons | not needed |
| Rijksmuseum, Europeana, Smithsonian (api.data.gov) | needed, enter it in the options |
| Unsplash, Pixabay (photos) | needed, free at [unsplash.com/developers](https://unsplash.com/developers) and [pixabay.com/api/docs](https://pixabay.com/api/docs/) |

Choose sources, API keys, the photo search terms for Unsplash and Pixabay (default `landscape`), how images that are not 16:9 are fitted (letterbox with black bars, the default, or crop to fill the screen), and the matte (passe-partout) under *Configure* on the integration.

In the media browser, the search field in the Unsplash and Pixabay folders asks the library itself for new photos instead of filtering the listed ones (needs a Home Assistant version whose media browser supports search).

Unsplash and Pixabay photos are licensed by their photographers under the Unsplash and Pixabay licenses; the photographer is shown as the artist.

## On the Frame

*Media → RemArt → On the Frame* lists the pictures stored in the TV's *My Photos*. The one currently shown comes first and is marked *(shown)*. Picking one shows it right away, without another upload. Thumbnails come from the TV and are cached. Images uploaded through RemArt keep their titles.

## Drag & drop card

The integration ships a dashboard card. Add it in the dashboard editor (*Add card → RemArt Frame*) or in YAML:

```yaml
type: custom:remart-frame-card
entity: media_player.living_room_frame
# title: Living room  # optional
```

Drop one or more images onto the card, or click it to choose files, and each image is shown on the Frame. Images dragged from another browser tab work too. Below the drop zone the card shows the pictures stored on the Frame; click one to show it, or use its trash icon to delete it from the TV after a confirmation.

The Frame entity also takes any image URL or media source item, e.g. in an automation:

```yaml
action: media_player.play_media
target:
  entity_id: media_player.living_room_frame
data:
  media_content_id: https://example.org/picture.jpg
  media_content_type: image/jpeg
```

## Troubleshooting

- **Cannot connect**: the TV must be on (or in art mode) and reachable on ports 8001 and 8002. If you declined the prompt, allow the device again under *TV settings → General → External device manager → Device connection manager*.
- **Image shows only after a while / not at all**: some firmwares do not acknowledge every request. Enable debug logging for `custom_components.remart` and `samsungtvws` and open an issue with the log.

## Development

```bash
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python pytest-homeassistant-custom-component "samsungtvws[async,encrypted]==3.0.6" hassil home-assistant-intents gazetteer-matcher ruff
.venv/bin/pytest
.venv/bin/ruff check custom_components tests
```

### Releasing

1. Bump `version` in `custom_components/remart/manifest.json` (and `pyproject.toml`).
2. Commit, then tag and push: `git tag v0.1.0 && git push origin v0.1.0`.
3. The *Release* workflow checks that the tag matches the manifest version and publishes a GitHub release, which HACS offers as an update.
