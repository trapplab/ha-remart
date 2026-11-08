"""Tests for the TV client (samsungtvws mocked)."""

import asyncio
from unittest.mock import patch

import pytest
from samsungtvws.exceptions import ConnectionFailure, ResponseError

from homeassistant.core import HomeAssistant

from custom_components.remart.frame import (
    FrameClient,
    FrameError,
    NotAFrameError,
)


@pytest.fixture
def art():
    """Mock SamsungTVArt; yields the instance."""
    with (
        patch("custom_components.remart.frame.SamsungTVArt") as cls,
        patch("custom_components.remart.frame.time.sleep"),
    ):
        instance = cls.return_value
        instance.token = None
        instance.upload.return_value = "MY_F0042"
        instance.get_artmode.return_value = "off"
        instance._get_rest_api.return_value.rest_device_info.return_value = {
            "device": {
                "FrameTVSupport": "true",
                "duid": "uuid:abc",
                "modelName": "QE65LS03",
                "name": "Frame",
            }
        }
        yield instance


async def test_show_full_flow(hass: HomeAssistant, art) -> None:
    """Upload with matte, art mode on, select the new image, close."""
    client = FrameClient("192.0.2.10", 8002, "tok", "none")
    assert await client.async_show(hass, b"jpeg") == "MY_F0042"
    art.upload.assert_called_once_with(
        b"jpeg", matte="none", portrait_matte="none", file_type="jpg"
    )
    art.set_artmode.assert_called_once_with("on")
    art.select_image.assert_called_once_with("MY_F0042", category="MY-C0002", show=True)
    art.close.assert_called_once()


async def test_show_skips_artmode_when_on(hass: HomeAssistant, art) -> None:
    """The TV does not ACK set_artmode when already on, so it is not sent."""
    art.get_artmode.return_value = "on"
    await FrameClient("h", 8002, None, "none").async_show(hass, b"jpeg")
    art.set_artmode.assert_not_called()


async def test_show_tolerates_missing_acks(hass: HomeAssistant, art) -> None:
    """Firmwares that never answer still count as success."""
    art.get_artmode.side_effect = ConnectionFailure("Websocket Time out")
    art.set_artmode.side_effect = ConnectionFailure("Websocket Time out")
    art.select_image.side_effect = ResponseError("no ack")
    assert (
        await FrameClient("h", 8002, None, "none").async_show(hass, b"jpeg")
        == "MY_F0042"
    )


async def test_show_failures(hass: HomeAssistant, art) -> None:
    """Connection and upload failures become FrameError and close the socket."""
    client = FrameClient("h", 8002, None, "none")
    art.open.side_effect = OSError("No route to host")
    with pytest.raises(FrameError, match="No route"):
        await client.async_show(hass, b"jpeg")
    art.open.side_effect = None
    art.upload.side_effect = ResponseError(
        "`send_image` request failed with error number -1"
    )
    with pytest.raises(FrameError, match="rejected"):
        await client.async_show(hass, b"jpeg")
    assert art.close.call_count == 2


async def test_show_keeps_new_token(hass: HomeAssistant, art) -> None:
    """A token handed out on connect is kept for the next call."""
    art.token = "fresh"
    client = FrameClient("h", 8002, None, "none")
    await client.async_show(hass, b"jpeg")
    assert client.token == "fresh"


def test_pair(art) -> None:
    """Pairing checks art support, opens once and returns device info."""
    art.token = "paired"
    client = FrameClient("h", 8002, None, "none")
    info = client.pair()
    assert (info.unique_id, info.model, info.name) == ("uuid:abc", "QE65LS03", "Frame")
    assert client.token == "paired"
    art.open.assert_called_once()


def test_pair_rejects_non_frame(art) -> None:
    """A regular Samsung TV is refused before any websocket prompt."""
    art._get_rest_api.return_value.rest_device_info.return_value = {
        "device": {"FrameTVSupport": "false"}
    }
    with pytest.raises(NotAFrameError):
        FrameClient("h", 8002, None, "none").pair()
    art.open.assert_not_called()


def test_pair_unreachable(art) -> None:
    """An unreachable TV is a FrameError."""
    art._get_rest_api.return_value.rest_device_info.side_effect = OSError("timeout")
    with pytest.raises(FrameError, match="Cannot reach"):
        FrameClient("h", 8002, None, "none").pair()


async def test_list_stored(hass: HomeAssistant, art) -> None:
    """Uploads are listed newest first with the shown content id."""
    art.available.return_value = [
        {"content_id": "MY_F0001", "image_date": "2026:01:01 10:00:00"},
        {"content_id": "MY_F0002", "image_date": "2026:03:01 10:00:00"},
        {"no_id": True},
    ]
    art.get_current.return_value = {"content_id": "MY_F0001"}
    stored, current = await FrameClient("h", 8002, None, "none").async_list(hass)
    assert [a.content_id for a in stored] == ["MY_F0002", "MY_F0001"]
    assert current == "MY_F0001"
    art.available.assert_called_once_with("MY-C0002")
    art.close.assert_called_once()


async def test_list_failures(hass: HomeAssistant, art) -> None:
    """A missing current image is fine; a failed list is a FrameError."""
    art.available.return_value = []
    art.get_current.side_effect = ConnectionFailure("Websocket Time out")
    client = FrameClient("h", 8002, None, "none")
    assert await client.async_list(hass) == ([], None)
    art.available.side_effect = ResponseError("error number -1")
    with pytest.raises(FrameError, match="no art list"):
        await client.async_list(hass)


async def test_select_stored(hass: HomeAssistant, art) -> None:
    """Selecting turns art mode on and shows the image without an upload."""
    await FrameClient("h", 8002, None, "none").async_select(hass, "MY_F0007")
    art.upload.assert_not_called()
    art.set_artmode.assert_called_once_with("on")
    art.select_image.assert_called_once_with("MY_F0007", category="MY-C0002", show=True)


async def test_thumbnails_are_batched_and_cached(hass: HomeAssistant, art) -> None:
    """Parallel requests share one connection; results are cached."""
    art.get_thumbnail.side_effect = lambda cid: (
        None if cid == "MY_F0003" else f"jpg-{cid}".encode()
    )
    client = FrameClient("h", 8002, None, "none")
    results = await asyncio.gather(
        *(client.async_thumbnail(hass, f"MY_F000{i}") for i in (1, 2, 3, 1))
    )
    assert results == [b"jpg-MY_F0001", b"jpg-MY_F0002", None, b"jpg-MY_F0001"]
    assert art.open.call_count == 1
    assert art.get_thumbnail.call_count == 3

    assert await client.async_thumbnail(hass, "MY_F0002") == b"jpg-MY_F0002"
    assert art.open.call_count == 1

    client.cache_thumbnail("MY_F0009", b"preview")
    assert await client.async_thumbnail(hass, "MY_F0009") == b"preview"


async def test_thumbnails_unreachable(hass: HomeAssistant, art) -> None:
    """An offline TV yields no thumbnail instead of an error."""
    art.open.side_effect = OSError("No route to host")
    client = FrameClient("h", 8002, None, "none")
    assert await client.async_thumbnail(hass, "MY_F0001") is None


async def test_delete_stored(hass: HomeAssistant, art) -> None:
    """Deleting removes the image on the TV and its cached thumbnail."""
    client = FrameClient("h", 8002, None, "none")
    client.cache_thumbnail("MY_F0001", b"thumb")
    art.delete.return_value = True
    await client.async_delete(hass, "MY_F0001")
    art.delete.assert_called_once_with("MY_F0001")
    art.close.assert_called_once()
    assert client.cached_thumbnail("MY_F0001") is None


async def test_delete_failures(hass: HomeAssistant, art) -> None:
    """A refused or failed delete raises FrameError."""
    client = FrameClient("h", 8002, None, "none")
    art.delete.return_value = False
    with pytest.raises(FrameError, match="did not delete"):
        await client.async_delete(hass, "MY_F0001")
    art.delete.side_effect = ConnectionFailure("gone")
    with pytest.raises(FrameError, match="failed"):
        await client.async_delete(hass, "MY_F0001")
    art.delete.side_effect = ResponseError("nope")
    with pytest.raises(FrameError, match="did not delete"):
        await client.async_delete(hass, "MY_F0001")
