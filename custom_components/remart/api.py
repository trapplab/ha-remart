"""HTTP and websocket endpoints for the Frame card and the media browser."""

from http import HTTPStatus
from pathlib import Path
from typing import Any

from aiohttp import BodyPartReader, web
import probatio

from homeassistant.components import frontend, websocket_api
from homeassistant.components.http import (
    KEY_HASS,
    HomeAssistantView,
    StaticPathConfig,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.loader import async_get_integration

from .const import DOMAIN
from .frame import FrameError
from .media_source import frame_identifier, thumbnail_url
from .models import RemArtConfigEntry

CARD_URL = f"/{DOMAIN}/remart-frame-card.js"
CARD_PATH = Path(__file__).parent / "frontend" / "remart-frame-card.js"

# Phone photos and scans; the Frame gets a 4K JPEG either way.
MAX_UPLOAD_BYTES = 60 * 1024 * 1024
CHUNK_SIZE = 256 * 1024


async def async_setup_api(hass: HomeAssistant) -> None:
    """Register the views, the websocket command and the card."""
    hass.http.register_view(ThumbnailView())
    hass.http.register_view(UploadView())
    websocket_api.async_register_command(hass, websocket_frame_art)
    websocket_api.async_register_command(hass, websocket_delete_art)
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(CARD_PATH), cache_headers=True)]
    )
    if "frontend" in hass.config.components:
        integration = await async_get_integration(hass, DOMAIN)
        frontend.add_extra_js_url(hass, f"{CARD_URL}?v={integration.version}")


def _loaded_entry(hass: HomeAssistant, entry_id: str) -> RemArtConfigEntry | None:
    entry = hass.config_entries.async_get_entry(entry_id)
    if (
        entry is None
        or entry.domain != DOMAIN
        or entry.state is not ConfigEntryState.LOADED
    ):
        return None
    return entry


def _image_type(data: bytes) -> str:
    if data.startswith(b"\x89PNG"):
        return "image/png"
    return "image/jpeg"


class ThumbnailView(HomeAssistantView):
    """Serve the thumbnail of an image stored on a Frame."""

    url = f"/api/{DOMAIN}/{{entry_id}}/thumbnail/{{content_id}}"
    name = f"api:{DOMAIN}:thumbnail"

    async def get(
        self, request: web.Request, entry_id: str, content_id: str
    ) -> web.Response:
        """Return the thumbnail, fetched from the TV once and then cached."""
        hass = request.app[KEY_HASS]
        if (entry := _loaded_entry(hass, entry_id)) is None:
            return web.Response(status=HTTPStatus.NOT_FOUND)
        data = await entry.runtime_data.frame.async_thumbnail(hass, content_id)
        if data is None:
            return web.Response(status=HTTPStatus.NOT_FOUND)
        return web.Response(
            body=data,
            content_type=_image_type(data),
            headers={"Cache-Control": "private, max-age=86400"},
        )


class UploadView(HomeAssistantView):
    """Accept an image file (e.g. dropped onto the card) and show it."""

    url = f"/api/{DOMAIN}/upload/{{entity_id}}"
    name = f"api:{DOMAIN}:upload"

    async def post(self, request: web.Request, entity_id: str) -> web.Response:
        """Read the "file" part of a multipart upload and send it to the Frame."""
        hass = request.app[KEY_HASS]
        entry = _entry_of_entity(hass, entity_id)
        if entry is None or (player := entry.runtime_data.player) is None:
            return self.json_message("Frame not set up", HTTPStatus.NOT_FOUND)

        filename: str | None = None
        data: bytes | None = None
        try:
            reader = await request.multipart()
            while (part := await reader.next()) is not None:
                if isinstance(part, BodyPartReader) and part.name == "file":
                    filename = part.filename
                    data = await _read_limited(part)
                    break
        except (AssertionError, ValueError, KeyError) as err:
            return self.json_message(
                f"Expected a multipart upload: {err}", HTTPStatus.BAD_REQUEST
            )
        if data is None:
            return self.json_message("No file in upload", HTTPStatus.BAD_REQUEST)
        if len(data) > MAX_UPLOAD_BYTES:
            return self.json_message(
                "Image is too large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE
            )

        title = Path(filename).stem if filename else None
        try:
            content_id = await player.async_show_image(data, title=title)
        except HomeAssistantError as err:
            return self.json_message(str(err), HTTPStatus.BAD_GATEWAY)
        return self.json({"content_id": content_id})


async def _read_limited(part: BodyPartReader) -> bytes:
    """Read a part, stopping one chunk past the size limit."""
    chunks: list[bytes] = []
    size = 0
    while chunk := await part.read_chunk(CHUNK_SIZE):
        chunks.append(chunk)
        size += len(chunk)
        if size > MAX_UPLOAD_BYTES:
            break
    return b"".join(chunks)


def _entry_of_entity(hass: HomeAssistant, entity_id: str) -> RemArtConfigEntry | None:
    entries: list[RemArtConfigEntry] = hass.config_entries.async_loaded_entries(DOMAIN)
    for entry in entries:
        player = entry.runtime_data.player
        if player is not None and player.entity_id == entity_id:
            return entry
    return None


@websocket_api.websocket_command(
    {
        probatio.Required("type"): f"{DOMAIN}/frame_art",
        probatio.Required("entity_id"): str,
    }
)
@websocket_api.async_response
async def websocket_frame_art(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """List the images stored on a Frame, the shown one first."""
    entry = _entry_of_entity(hass, msg["entity_id"])
    if entry is None:
        connection.send_error(
            msg["id"], websocket_api.ERR_NOT_FOUND, "Not a RemArt Frame"
        )
        return
    entry_id = entry.entry_id
    data = entry.runtime_data
    try:
        items = await data.catalog.async_list(data.frame)
    except FrameError as err:
        connection.send_error(msg["id"], "frame_unavailable", str(err))
        return
    connection.send_result(
        msg["id"],
        {
            "entry_id": entry_id,
            "items": [
                {
                    "content_id": art.content_id,
                    "title": art.title,
                    "artist": art.artist,
                    "current": art.current,
                    "media_content_id": (
                        f"media-source://{DOMAIN}/"
                        f"{frame_identifier(entry_id, art.content_id)}"
                    ),
                    "thumbnail": thumbnail_url(entry_id, art.content_id),
                }
                for art in items
            ],
        },
    )


@websocket_api.websocket_command(
    {
        probatio.Required("type"): f"{DOMAIN}/delete_art",
        probatio.Required("entity_id"): str,
        probatio.Required("content_id"): str,
    }
)
@websocket_api.async_response
async def websocket_delete_art(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete an image stored on a Frame."""
    entry = _entry_of_entity(hass, msg["entity_id"])
    if entry is None:
        connection.send_error(
            msg["id"], websocket_api.ERR_NOT_FOUND, "Not a RemArt Frame"
        )
        return
    data = entry.runtime_data
    try:
        await data.frame.async_delete(hass, msg["content_id"])
    except FrameError as err:
        connection.send_error(msg["id"], "frame_unavailable", str(err))
        return
    data.catalog.forget(msg["content_id"])
    connection.send_result(msg["id"])
