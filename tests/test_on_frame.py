"""Tests for the images stored on the Frame, the card endpoints and uploads."""

from http import HTTPStatus
import io
from unittest.mock import AsyncMock, patch

import aiohttp
from PIL import Image
import pytest

from homeassistant.components import media_source
from homeassistant.components.media_player import (
    ATTR_MEDIA_CONTENT_ID,
    ATTR_MEDIA_CONTENT_TYPE,
    DOMAIN as MP_DOMAIN,
    SERVICE_PLAY_MEDIA,
)
from homeassistant.components.media_player.errors import BrowseError
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant

from custom_components.remart.frame import FrameError, StoredArt

from .conftest import png_bytes

ENTITY_ID = "media_player.living_room_frame"
STORED = [StoredArt("MY_F0002", "2026:03:01"), StoredArt("MY_F0001", "2026:01:01")]


@pytest.fixture
def mock_list():
    """Patch the TV's art list; MY_F0001 is shown."""
    with patch(
        "custom_components.remart.frame.FrameClient.async_list",
        new=AsyncMock(return_value=(STORED, "MY_F0001")),
    ) as mock:
        yield mock


@pytest.fixture
def mock_select():
    """Patch selecting a stored image."""
    with patch(
        "custom_components.remart.frame.FrameClient.async_select", new=AsyncMock()
    ) as mock:
        yield mock


@pytest.fixture
def mock_thumbnail():
    """Patch thumbnails from the TV."""
    with patch(
        "custom_components.remart.frame.FrameClient.async_thumbnail",
        new=AsyncMock(return_value=b"\xff\xd8thumb"),
    ) as mock:
        yield mock


def _size(jpeg: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(jpeg)) as image:
        return image.size


async def test_browse_on_frame(
    hass: HomeAssistant, setup_entry, mock_list, mock_show, aioclient_mock
) -> None:
    """The shown image comes first; uploads keep their titles."""
    aioclient_mock.get("https://example.org/ok.png", content=png_bytes(1600, 900))
    mock_show.return_value = "MY_F0002"
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
    setup_entry.runtime_data.catalog.add("MY_F0002", "Sunset", "Me")

    folder_id = f"media-source://remart/on_frame/{setup_entry.entry_id}"
    folder = await media_source.async_browse_media(hass, folder_id)
    assert folder.title == "On the Frame – Living Room Frame"
    shown, other = folder.children
    assert shown.title == "MY_F0001 (shown)"
    assert shown.media_content_id == f"{folder_id}/MY_F0001"
    assert shown.thumbnail == (f"/api/remart/{setup_entry.entry_id}/thumbnail/MY_F0001")
    assert other.title == "Sunset – Me"

    mock_list.side_effect = FrameError("TV is off")
    with pytest.raises(BrowseError, match="TV is off"):
        await media_source.async_browse_media(hass, folder_id)


async def test_catalog_is_pruned(hass: HomeAssistant, setup_entry, mock_list) -> None:
    """Titles of images deleted on the TV are forgotten."""
    catalog = setup_entry.runtime_data.catalog
    catalog.add("MY_F0001", "Kept", None)
    catalog.add("MY_F0099", "Deleted", None)
    await media_source.async_browse_media(
        hass, f"media-source://remart/on_frame/{setup_entry.entry_id}"
    )
    assert catalog.get("MY_F0001")
    assert catalog.get("MY_F0099") is None


async def test_play_stored_selects_it(
    hass: HomeAssistant, setup_entry, mock_show, mock_select, mock_thumbnail
) -> None:
    """A stored image is selected on the TV, not uploaded again."""
    setup_entry.runtime_data.catalog.add("MY_F0001", "Sunset", "Me")
    media_id = f"media-source://remart/on_frame/{setup_entry.entry_id}/MY_F0001"
    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_PLAY_MEDIA,
        {
            ATTR_ENTITY_ID: ENTITY_ID,
            ATTR_MEDIA_CONTENT_ID: media_id,
            ATTR_MEDIA_CONTENT_TYPE: "image/jpeg",
        },
        blocking=True,
    )
    assert mock_select.await_args.args[1] == "MY_F0001"
    mock_show.assert_not_awaited()
    state = hass.states.get(ENTITY_ID)
    assert state.attributes["media_title"] == "Sunset"
    assert state.attributes["media_content_id"] == media_id
    assert state.attributes["entity_picture"]

    # Other players get the thumbnail.
    play = await media_source.async_resolve_media(hass, media_id, None)
    assert play.url == f"/api/remart/{setup_entry.entry_id}/thumbnail/MY_F0001"


async def test_thumbnail_view(
    hass: HomeAssistant, setup_entry, mock_thumbnail, hass_client
) -> None:
    """Thumbnails are served to logged-in users only."""
    client = await hass_client()
    url = f"/api/remart/{setup_entry.entry_id}/thumbnail/MY_F0001"
    resp = await client.get(url)
    assert resp.status == HTTPStatus.OK
    assert resp.content_type == "image/jpeg"
    assert await resp.read() == b"\xff\xd8thumb"

    mock_thumbnail.return_value = None
    assert (await client.get(url)).status == HTTPStatus.NOT_FOUND
    resp = await client.get("/api/remart/nope/thumbnail/MY_F0001")
    assert resp.status == HTTPStatus.NOT_FOUND


async def test_upload(hass: HomeAssistant, setup_entry, mock_show, hass_client) -> None:
    """A dropped file is fitted, uploaded and titled after its name."""
    client = await hass_client()
    form = aiohttp.FormData()
    form.add_field(
        "file", png_bytes(900, 1200), filename="Holiday.png", content_type="image/png"
    )
    resp = await client.post(f"/api/remart/upload/{ENTITY_ID}", data=form)
    assert resp.status == HTTPStatus.OK
    assert await resp.json() == {"content_id": "MY_F0001"}
    assert _size(mock_show.await_args.args[1]) == (2133, 1200)
    assert hass.states.get(ENTITY_ID).attributes["media_title"] == "Holiday"
    assert setup_entry.runtime_data.catalog.get("MY_F0001")["title"] == "Holiday"
    # The preview doubles as thumbnail, so the TV is not asked.
    assert await setup_entry.runtime_data.frame.async_thumbnail(hass, "MY_F0001")


async def test_upload_errors(
    hass: HomeAssistant, setup_entry, mock_show, hass_client
) -> None:
    """Bad uploads are rejected with a message."""
    client = await hass_client()

    async def post(entity_id: str, content: bytes | None) -> aiohttp.ClientResponse:
        form = aiohttp.FormData()
        if content is None:
            form.add_field("other", "x")
        else:
            form.add_field("file", content, filename="x.jpg")
        return await client.post(f"/api/remart/upload/{entity_id}", data=form)

    assert (await post("media_player.other", b"x")).status == HTTPStatus.NOT_FOUND
    assert (await post(ENTITY_ID, None)).status == HTTPStatus.BAD_REQUEST
    resp = await client.post(
        f"/api/remart/upload/{ENTITY_ID}",
        data=b"garbage",
        headers={"Content-Type": "text/plain"},
    )
    assert resp.status == HTTPStatus.BAD_REQUEST
    resp = await post(ENTITY_ID, b"not an image")
    assert resp.status == HTTPStatus.BAD_GATEWAY
    assert "Not a usable image" in (await resp.json())["message"]

    with patch("custom_components.remart.api.MAX_UPLOAD_BYTES", 10):
        resp = await post(ENTITY_ID, png_bytes(100, 100))
    assert resp.status == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    mock_show.assert_not_awaited()


async def test_websocket_frame_art(
    hass: HomeAssistant, setup_entry, mock_list, hass_ws_client
) -> None:
    """The card gets the stored images with play ids and thumbnail URLs."""
    setup_entry.runtime_data.catalog.add("MY_F0002", "Sunset", "Me")
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "remart/frame_art", "entity_id": ENTITY_ID})
    msg = await client.receive_json()
    assert msg["success"]
    entry_id = setup_entry.entry_id
    assert msg["result"] == {
        "entry_id": entry_id,
        "items": [
            {
                "content_id": "MY_F0001",
                "title": None,
                "artist": None,
                "current": True,
                "deletable": True,
                "media_content_id": (
                    f"media-source://remart/on_frame/{entry_id}/MY_F0001"
                ),
                "thumbnail": f"/api/remart/{entry_id}/thumbnail/MY_F0001",
            },
            {
                "content_id": "MY_F0002",
                "title": "Sunset",
                "artist": "Me",
                "current": False,
                "deletable": True,
                "media_content_id": (
                    f"media-source://remart/on_frame/{entry_id}/MY_F0002"
                ),
                "thumbnail": f"/api/remart/{entry_id}/thumbnail/MY_F0002",
            },
        ],
    }

    await client.send_json_auto_id(
        {"type": "remart/frame_art", "entity_id": "media_player.other"}
    )
    msg = await client.receive_json()
    assert msg["error"]["code"] == "not_found"

    mock_list.side_effect = FrameError("TV is off")
    await client.send_json_auto_id({"type": "remart/frame_art", "entity_id": ENTITY_ID})
    msg = await client.receive_json()
    assert msg["error"] == {"code": "frame_unavailable", "message": "TV is off"}


async def test_websocket_delete_art(
    hass: HomeAssistant, setup_entry, hass_ws_client
) -> None:
    """The card deletes an image on the TV and its title is forgotten."""
    catalog = setup_entry.runtime_data.catalog
    catalog.add("MY_F0002", "Sunset", "Me")
    client = await hass_ws_client(hass)
    with patch(
        "custom_components.remart.frame.FrameClient.async_delete", new=AsyncMock()
    ) as mock_delete:
        await client.send_json_auto_id(
            {
                "type": "remart/delete_art",
                "entity_id": ENTITY_ID,
                "content_id": "MY_F0002",
            }
        )
        msg = await client.receive_json()
        assert msg["success"]
        mock_delete.assert_awaited_once()
        assert mock_delete.await_args.args[1] == "MY_F0002"
        assert catalog.get("MY_F0002") is None

        await client.send_json_auto_id(
            {
                "type": "remart/delete_art",
                "entity_id": "media_player.other",
                "content_id": "MY_F0002",
            }
        )
        msg = await client.receive_json()
        assert msg["error"]["code"] == "not_found"

        catalog.add("MY_F0001", "Kept", None)
        mock_delete.side_effect = FrameError("TV is off")
        await client.send_json_auto_id(
            {
                "type": "remart/delete_art",
                "entity_id": ENTITY_ID,
                "content_id": "MY_F0001",
            }
        )
        msg = await client.receive_json()
        assert msg["error"] == {"code": "frame_unavailable", "message": "TV is off"}
        assert catalog.get("MY_F0001") is not None

        mock_delete.reset_mock()
        await client.send_json_auto_id(
            {
                "type": "remart/delete_art",
                "entity_id": ENTITY_ID,
                "content_id": "SAM-S0700",
            }
        )
        msg = await client.receive_json()
        assert msg["error"]["code"] == "not_deletable"
        mock_delete.assert_not_awaited()


async def test_card_is_served(hass: HomeAssistant, setup_entry, hass_client) -> None:
    """The Lovelace card ships with the integration."""
    client = await hass_client()
    resp = await client.get("/remart/remart-frame-card.js")
    assert resp.status == HTTPStatus.OK
    assert "remart-frame-card" in await resp.text()
