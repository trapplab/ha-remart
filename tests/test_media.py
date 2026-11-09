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
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

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
    assert [c.title for c in root.children] == [
        "On the Frame",
        "Art Institute of Chicago",
    ]
    assert root.children[0].media_content_id == (
        f"media-source://remart/on_frame/{setup_entry.entry_id}"
    )

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


async def test_search_photos(
    hass: HomeAssistant, aioclient_mock, config_entry, mock_show, mock_page
) -> None:
    """A search asks Pixabay again and its hits resolve and page like a browse."""
    from dataclasses import replace

    import aiohttp

    from homeassistant.components.media_player import (
        BrowseError,
        MediaClass,
        SearchMediaQuery,
    )
    from homeassistant.setup import async_setup_component

    from .conftest import ARTWORK

    hass.config_entries.async_update_entry(
        config_entry,
        options={"sources": ["chicago", "pixabay"], "pixabay_api_key": "key"},
    )
    assert await async_setup_component(hass, "media_source", {})
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    hit = replace(ARTWORK, id="7", source_id="pixabay", title="Fog")
    with patch(
        "custom_components.remart.sources.photos.PixabaySource.search_page",
        return_value=[hit],
    ) as search:
        pixabay = await media_source.async_browse_media(
            hass, "media-source://remart/pixabay"
        )
        assert pixabay.can_search
        assert search.call_args.args == ("landscape", 1, 20)

        found = await media_source.async_search_media(
            hass,
            "media-source://remart/pixabay",
            SearchMediaQuery(search_query=" foggy / forest "),
        )
        art, nxt = found.result
        assert search.call_args.args == ("foggy / forest", 1, 20)
        assert art.media_content_id == (
            "media-source://remart/pixabay@foggy%20%2F%20forest/1/7"
        )
        assert nxt.media_content_id == (
            "media-source://remart/pixabay@foggy%20%2F%20forest/2"
        )

        page = await media_source.async_browse_media(hass, nxt.media_content_id)
        assert page.title == "Pixabay: foggy / forest – Page 2"
        assert page.can_search
        assert search.call_args.args == ("foggy / forest", 2, 20)

        play = await media_source.async_resolve_media(hass, art.media_content_id, None)
        assert play.url == "https://example.org/bedroom.jpg"
        assert search.call_count == 3

    page = await media_source.async_browse_media(
        hass, "media-source://remart/pixabay@%20/1"
    )
    assert page.media_content_id == "media-source://remart/pixabay/1"

    videos = await media_source.async_search_media(
        hass,
        "media-source://remart/pixabay",
        SearchMediaQuery(search_query="fog", media_filter_classes=[MediaClass.VIDEO]),
    )
    assert videos.result == []

    with (
        patch(
            "custom_components.remart.sources.photos.PixabaySource.search_page",
            side_effect=aiohttp.ClientResponseError(
                None, (), status=429, message="Too Many Requests"
            ),
        ),
        pytest.raises(BrowseError, match="429 Too Many Requests"),
    ):
        await media_source.async_search_media(
            hass, "media-source://remart/pixabay", SearchMediaQuery(search_query="sea")
        )

    chicago = await media_source.async_browse_media(
        hass, "media-source://remart/chicago"
    )
    assert not chicago.can_search
    with pytest.raises(BrowseError):
        await media_source.async_search_media(
            hass, "media-source://remart/chicago", SearchMediaQuery(search_query="x")
        )


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


async def test_play_artwork_cropped(
    hass: HomeAssistant, setup_entry, mock_show, aioclient_mock
) -> None:
    """With the crop option the image fills 16:9 instead of being letterboxed."""
    hass.config_entries.async_update_entry(
        setup_entry, options={**setup_entry.options, "fit": "crop"}
    )
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
    assert _image_size(jpeg) == (900, 506)


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
