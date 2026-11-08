"""Tests for browsing the gallery and showing images on the Frame."""

import io
from unittest.mock import patch

from PIL import Image
import pytest

from homeassistant.components import media_source
from homeassistant.components.media_player import (
    ATTR_MEDIA_CONTENT_ID,
    ATTR_MEDIA_CONTENT_TYPE,
    DOMAIN as MP_DOMAIN,
    SERVICE_PLAY_MEDIA,
)
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError

from custom_components.remart.const import DOMAIN
from custom_components.remart.frame import FrameError

from .conftest import png_bytes

ENTITY_ID = "media_player.living_room_frame"
ARTWORK_ID = "media-source://remart/chicago/1/28560"


def _image_size(jpeg: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(jpeg)) as image:
        return image.size


async def test_browse(hass: HomeAssistant, setup_entry, mock_page) -> None:
    """Root lists sources, a source lists artworks plus a next page link."""
    root = await media_source.async_browse_media(hass, "media-source://remart")
    assert [c.title for c in root.children] == ["Art Institute of Chicago"]

    page = await media_source.async_browse_media(hass, "media-source://remart/chicago")
    art, nxt = page.children
    assert art.media_content_id == ARTWORK_ID
    assert art.title == "The Bedroom – Vincent van Gogh"
    assert art.thumbnail == "https://example.org/bedroom_thumb.jpg"
    assert art.can_play and not art.can_expand
    assert nxt.media_content_id == "media-source://remart/chicago/2"
    assert nxt.can_expand

    # Page 1 was cached by the first browse.
    await media_source.async_browse_media(hass, "media-source://remart/chicago/1")
    assert mock_page.await_count == 1


async def test_artwork_ids_with_slashes(
    hass: HomeAssistant, setup_entry, mock_page
) -> None:
    """Europeana-style ids survive the round trip through the identifier."""
    from dataclasses import replace

    from .conftest import ARTWORK

    mock_page.return_value = [replace(ARTWORK, id="/2048/abc")]
    page = await media_source.async_browse_media(hass, "media-source://remart/chicago")
    media_id = page.children[0].media_content_id
    assert media_id == "media-source://remart/chicago/1/%2F2048%2Fabc"
    play = await media_source.async_resolve_media(hass, media_id, None)
    assert play.url == "https://example.org/bedroom.jpg"


async def test_play_artwork(
    hass: HomeAssistant, setup_entry, mock_show, aioclient_mock
) -> None:
    """Playing a gallery item downloads, fits to 16:9 and uploads it."""
    aioclient_mock.get("https://example.org/bedroom.jpg", content=png_bytes(900, 1200))
    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_PLAY_MEDIA,
        {
            ATTR_ENTITY_ID: ENTITY_ID,
            ATTR_MEDIA_CONTENT_ID: ARTWORK_ID,
            ATTR_MEDIA_CONTENT_TYPE: "image/jpeg",
        },
        blocking=True,
    )
    jpeg = mock_show.await_args.args[1]
    assert _image_size(jpeg) == (2133, 1200)

    state = hass.states.get(ENTITY_ID)
    assert state.state == "on"
    assert state.attributes["media_title"] == "The Bedroom"
    assert state.attributes["media_artist"] == "Vincent van Gogh"
    assert state.attributes["entity_picture"].startswith("/api/media_player_proxy/")


async def test_play_url_and_errors(
    hass: HomeAssistant, setup_entry, mock_show, aioclient_mock
) -> None:
    """Plain URLs work; bad images and TV errors become HomeAssistantError."""
    aioclient_mock.get("https://example.org/ok.png", content=png_bytes(1600, 900))
    aioclient_mock.get("https://example.org/broken.jpg", content=b"not an image")

    async def play(url: str) -> None:
        await hass.services.async_call(
            MP_DOMAIN,
            SERVICE_PLAY_MEDIA,
            {
                ATTR_ENTITY_ID: ENTITY_ID,
                ATTR_MEDIA_CONTENT_ID: url,
                ATTR_MEDIA_CONTENT_TYPE: "image",
            },
            blocking=True,
        )

    await play("https://example.org/ok.png")
    assert _image_size(mock_show.await_args.args[1]) == (1600, 900)

    with pytest.raises(HomeAssistantError, match="Not a usable image"):
        await play("https://example.org/broken.jpg")

    mock_show.side_effect = FrameError("TV is off")
    with pytest.raises(HomeAssistantError, match="TV is off"):
        await play("https://example.org/ok.png")


async def test_token_is_persisted(
    hass: HomeAssistant, setup_entry, mock_show, aioclient_mock
) -> None:
    """A token the TV hands out during an upload is saved to the entry."""
    aioclient_mock.get("https://example.org/ok.png", content=png_bytes(1600, 900))

    async def show(self_hass, jpeg):
        setup_entry.runtime_data.frame.token = "rotated"
        return "MY_F0002"

    mock_show.side_effect = show
    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_PLAY_MEDIA,
        {
            ATTR_ENTITY_ID: ENTITY_ID,
            ATTR_MEDIA_CONTENT_ID: "https://example.org/ok.png",
            ATTR_MEDIA_CONTENT_TYPE: "image",
        },
        blocking=True,
    )
    assert setup_entry.data["token"] == "rotated"


@pytest.fixture
async def fake_ai_task(hass: HomeAssistant, tmp_path):
    """Register ai_task.generate_image writing a PNG into a local media dir."""
    hass.config.media_dirs = {"local": str(tmp_path)}
    (tmp_path / "ai.png").write_bytes(png_bytes(1024, 1024, (10, 120, 200)))
    calls: list[ServiceCall] = []

    async def generate(call: ServiceCall):
        calls.append(call)
        return {
            "media_source_id": "media-source://media_source/local/ai.png",
            "revised_prompt": "revised: " + call.data["instructions"],
            "model": "gpt-image-1",
        }

    hass.services.async_register(
        "ai_task", "generate_image", generate, supports_response=SupportsResponse.ONLY
    )
    return calls


async def test_generate_and_show(
    hass: HomeAssistant, fake_ai_task, setup_entry, mock_show
) -> None:
    """The service prompts AI Task, then shows the local result on the Frame."""
    response = await hass.services.async_call(
        DOMAIN,
        "generate_and_show",
        {ATTR_ENTITY_ID: ENTITY_ID, "description": "a lighthouse in a storm"},
        blocking=True,
        return_response=True,
    )
    (call,) = fake_ai_task
    assert call.data["instructions"].endswith("Subject: a lighthouse in a storm")
    assert "entity_id" not in call.data
    assert response[ENTITY_ID]["content_id"] == "MY_F0001"
    assert response[ENTITY_ID]["revised_prompt"].startswith("revised: ")
    assert _image_size(mock_show.await_args.args[1]) == (1820, 1024)

    state = hass.states.get(ENTITY_ID)
    assert state.attributes["media_title"] == "a lighthouse in a storm"
    assert state.attributes["media_artist"] == "gpt-image-1"


async def test_generate_timeout(hass: HomeAssistant, setup_entry, mock_show) -> None:
    """A hanging image model is reported, not waited on forever."""

    async def hang(call):
        import asyncio

        await asyncio.sleep(3600)

    hass.services.async_register(
        "ai_task", "generate_image", hang, supports_response=SupportsResponse.ONLY
    )
    with (
        patch("custom_components.remart.media_player.GENERATE_TIMEOUT", 0.05),
        pytest.raises(HomeAssistantError, match="longer than"),
    ):
        await hass.services.async_call(
            DOMAIN,
            "generate_and_show",
            {ATTR_ENTITY_ID: ENTITY_ID, "description": "x"},
            blocking=True,
            return_response=True,
        )
    mock_show.assert_not_awaited()
