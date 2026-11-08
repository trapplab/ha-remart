# RemArt Frame for Home Assistant

Show art on a Samsung Frame TV from Home Assistant:

- **Gallery**: browse public-domain artworks from nine museum sources and photos from Unsplash and Pixabay in the media browser and send one to the Frame with a click.
- **Drag & drop**: drop your own pictures onto the RemArt Frame card to show them on the TV.
- **On the Frame**: see the images stored on the TV, with the one currently shown first, and switch between them without uploading again.
- **AI art by voice**: tell your voice assistant what you want to see. Home Assistant generates the image and shows it on the Frame.

Images are letterboxed to 16:9 on black before upload, so the Frame never stretches them.

## Requirements

- Home Assistant 2026.10 or newer
- A Samsung Frame TV (2018 or newer) on the same network
- For AI art: an AI Task entity that can generate images (see below)

## Installation

**HACS**: add this repository as a custom repository (type *Integration*), install **RemArt Frame** and restart Home Assistant.

**Manual**: copy `custom_components/remart` into your `config/custom_components/` folder and restart.

Then go to *Settings → Devices & services → Add integration → RemArt Frame*, enter the TV's IP address and **accept the prompt on the TV** with the remote within 30 seconds.

## Gallery

Open *Media* in the sidebar, pick the Frame as the target player (bottom right), then *RemArt → a source → an artwork*. The image appears on the Frame in art mode.

| Source | API key |
| --- | --- |
| Art Institute of Chicago, The Met (European Paintings), Cleveland Museum of Art, SMK, Minneapolis Institute of Art, Wikimedia Commons | not needed |
| Rijksmuseum, Europeana, Smithsonian (api.data.gov) | needed, enter it in the options |
| Unsplash, Pixabay (photos) | needed, free at [unsplash.com/developers](https://unsplash.com/developers) and [pixabay.com/api/docs](https://pixabay.com/api/docs/) |

Choose sources, API keys, the photo search terms for Unsplash and Pixabay (default `landscape`), the matte (passe-partout) and the image prompt prefix under *Configure* on the integration.

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

Drop one or more images onto the card, or click it to choose files, and each image is shown on the Frame. Images dragged from another browser tab work too. Below the drop zone the card shows the pictures stored on the Frame; click one to show it.

The Frame entity also takes any image URL or media source item, e.g. in an automation:

```yaml
action: media_player.play_media
target:
  entity_id: media_player.living_room_frame
data:
  media_content_id: https://example.org/picture.jpg
  media_content_type: image/jpeg
```

## AI art

### 1. Set up an image generator

Set up an integration that provides AI Task image generation, for example **OpenAI** (needs an API key; each image is billed by OpenAI) or **Google Gemini**. Add an *AI Task* service to it and choose it as the preferred entity for **generating images** in Home Assistant's AI Task settings. Alternatively, pass the entity explicitly with `ai_task_entity` (see below).

### 2. Try it

*Developer tools → Actions*:

```yaml
action: remart.generate_and_show
target:
  entity_id: media_player.living_room_frame
data:
  description: A lighthouse in a storm in the style of William Turner
  # ai_task_entity: ai_task.openai_ai_task  # optional, defaults to the preferred entity
```

The response contains the TV's `content_id`, the generated image's `media_source_id` and the prompt the model actually used. Generated images are also kept in *Media → AI generated images*.

### 3. Use it by voice

Use a conversation agent that is backed by an LLM (OpenAI, Google Gemini, Anthropic, Ollama …) with **Control Home Assistant → Assist** enabled, and **expose the Frame entity** to Assist (*Settings → Voice assistants → Expose*). The agent then gets a `GenerateFrameArt` tool and you can say things like:

> "Paint me a foggy autumn forest in the style of Caspar David Friedrich on the Frame."

Generating takes 10–60 seconds; the assistant answers when the picture is on the TV.

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
