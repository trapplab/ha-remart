"""The Frame as a media player that 'plays' images in art mode."""

import asyncio
from typing import Any

import aiohttp
from PIL import Image, UnidentifiedImageError

from homeassistant.components import media_source
from homeassistant.components.media_player import (
    BrowseMedia,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
    async_process_play_media_url,
)
from homeassistant.core import HomeAssistant, ServiceResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CONF_PROMPT_PREFIX,
    CONF_TOKEN,
    DEFAULT_PROMPT_PREFIX,
    DOMAIN,
    GENERATE_TIMEOUT,
)
from .frame import FrameError
from .imaging import fit_to_frame, make_preview
from .media_source import parse_frame_identifier, parse_identifier
from .models import RemArtConfigEntry
from .sources import Artwork

DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(total=60)
MAX_DOWNLOAD_BYTES = 60 * 1024 * 1024


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RemArtConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Frame media player."""
    player = FrameArtPlayer(entry)
    entry.runtime_data.player = player
    async_add_entities([player])


class FrameArtPlayer(MediaPlayerEntity):
    """Shows images on the Frame. Anything played ends up in art mode."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False
    _attr_media_content_type = MediaType.IMAGE
    _attr_supported_features = (
        MediaPlayerEntityFeature.PLAY_MEDIA | MediaPlayerEntityFeature.BROWSE_MEDIA
    )
    _attr_state = MediaPlayerState.IDLE

    def __init__(self, entry: RemArtConfigEntry) -> None:
        """Initialize the player."""
        self._entry = entry
        self._frame = entry.runtime_data.frame
        self._gallery = entry.runtime_data.gallery
        self._catalog = entry.runtime_data.catalog
        self._preview: bytes | None = None
        self._shown_content_id: str | None = None
        self._attr_unique_id = entry.unique_id or entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            manufacturer="Samsung",
            model=entry.data.get("model"),
            name=entry.title,
        )

    async def async_browse_media(
        self,
        media_content_type: MediaType | str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        """Browse images from all media sources."""
        return await media_source.async_browse_media(
            self.hass,
            media_content_id,
            content_filter=lambda item: item.media_content_type.startswith("image/"),
        )

    async def async_play_media(
        self, media_type: MediaType | str, media_id: str, **kwargs: Any
    ) -> None:
        """Show an image (URL or media source id) on the Frame."""
        await self.async_display(media_id)

    async def async_get_media_image(self) -> tuple[bytes | None, str | None]:
        """Return a preview of what the Frame shows."""
        if self._preview is None:
            return None, None
        return self._preview, "image/jpeg"

    async def async_display(
        self, media_id: str, *, title: str | None = None, artist: str | None = None
    ) -> str:
        """Load, fit and upload an image, then show it. Returns the content id."""
        artwork: Artwork | None = None
        if media_source.is_media_source_id(media_id):
            item = media_source.MediaSourceItem.from_uri(self.hass, media_id, None)
            if item.domain == DOMAIN:
                stored = parse_frame_identifier(item.identifier)
                if stored and stored[0] == self._entry.entry_id and stored[1]:
                    await self.async_select_stored(stored[1], media_id)
                    return stored[1]
                if stored is None:
                    artwork = await self._async_gallery_artwork(item.identifier)
            if artwork:
                title, artist = artwork.title, artwork.artist
            play = await media_source.async_resolve_media(
                self.hass, media_id, self.entity_id
            )
            if play.path:
                data = await self.hass.async_add_executor_job(play.path.read_bytes)
            else:
                data = await self._async_download(
                    async_process_play_media_url(self.hass, play.url)
                )
        else:
            data = await self._async_download(media_id)

        content_id = await self.async_show_image(
            data, media_id=media_id, title=title, artist=artist
        )
        if artwork:
            self.hass.async_create_background_task(
                self._gallery.async_track_use(artwork), "remart track use"
            )
        return content_id

    async def async_show_image(
        self,
        data: bytes,
        *,
        media_id: str | None = None,
        title: str | None = None,
        artist: str | None = None,
    ) -> str:
        """Fit and upload image bytes, then show them. Returns the content id."""
        try:
            jpeg, preview = await self.hass.async_add_executor_job(_prepare, data)
        except (
            UnidentifiedImageError,
            Image.DecompressionBombError,
            OSError,
            ValueError,
        ) as err:
            raise HomeAssistantError(f"Not a usable image: {err}") from err

        try:
            content_id = await self._frame.async_show(self.hass, jpeg)
        except FrameError as err:
            raise HomeAssistantError(str(err)) from err
        self._async_store_token()
        self._frame.cache_thumbnail(content_id, preview)
        self._catalog.add(content_id, title, artist)
        self._set_shown(content_id, media_id, preview, title, artist)
        return content_id

    async def async_select_stored(
        self, content_id: str, media_id: str | None = None
    ) -> None:
        """Show an image that is already on the Frame."""
        try:
            await self._frame.async_select(self.hass, content_id)
        except FrameError as err:
            raise HomeAssistantError(str(err)) from err
        known = self._catalog.get(content_id)
        preview = self._frame.cached_thumbnail(content_id)
        self._set_shown(
            content_id,
            media_id,
            preview,
            known["title"] if known else None,
            known["artist"] if known else None,
        )
        if preview is None:
            self.hass.async_create_background_task(
                self._async_load_preview(content_id), "remart preview"
            )

    async def _async_load_preview(self, content_id: str) -> None:
        """Fetch the thumbnail of a selected image for the entity picture."""
        preview = await self._frame.async_thumbnail(self.hass, content_id)
        if preview is None or self._attr_media_image_hash is not None:
            return
        if self._shown_content_id != content_id:
            return
        self._preview = preview
        self._attr_media_image_hash = content_id
        self.async_write_ha_state()

    def _set_shown(
        self,
        content_id: str,
        media_id: str | None,
        preview: bytes | None,
        title: str | None,
        artist: str | None,
    ) -> None:
        self._shown_content_id = content_id
        self._preview = preview
        self._attr_media_image_hash = content_id if preview else None
        self._attr_media_content_id = media_id or content_id
        self._attr_media_title = title
        self._attr_media_artist = artist
        self._attr_state = MediaPlayerState.ON
        self.async_write_ha_state()

    async def async_generate_and_show(
        self, description: str, ai_task_entity: str | None = None
    ) -> ServiceResponse:
        """Generate an image with AI Task and show it on the Frame."""
        prefix = self._entry.options.get(CONF_PROMPT_PREFIX, DEFAULT_PROMPT_PREFIX)
        data: dict[str, Any] = {
            "task_name": "frame art",
            "instructions": f"{prefix}{description}",
        }
        if ai_task_entity:
            data["entity_id"] = ai_task_entity
        try:
            async with asyncio.timeout(GENERATE_TIMEOUT):
                result = await self.hass.services.async_call(
                    "ai_task",
                    "generate_image",
                    data,
                    blocking=True,
                    context=self._context,
                    return_response=True,
                )
        except TimeoutError as err:
            raise HomeAssistantError(
                f"Image generation took longer than {GENERATE_TIMEOUT} s"
            ) from err
        assert isinstance(result, dict)
        media_source_id = str(result["media_source_id"])
        content_id = await self.async_display(
            media_source_id, title=description, artist=str(result.get("model") or "AI")
        )
        return {
            "content_id": content_id,
            "media_source_id": media_source_id,
            "revised_prompt": result.get("revised_prompt"),
        }

    async def _async_gallery_artwork(self, identifier: str) -> Artwork | None:
        parsed = parse_identifier(identifier)
        if parsed.artwork_id is None:
            return None
        return await self._gallery.async_get_artwork(
            parsed.source_id, parsed.page, parsed.artwork_id, parsed.query
        )

    async def _async_download(self, url: str) -> bytes:
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(url, timeout=DOWNLOAD_TIMEOUT) as resp:
                resp.raise_for_status()
                if int(resp.headers.get("Content-Length") or 0) > MAX_DOWNLOAD_BYTES:
                    raise HomeAssistantError(f"Image at {url} is too large")
                data = await resp.read()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise HomeAssistantError(f"Cannot download {url}: {err}") from err
        if len(data) > MAX_DOWNLOAD_BYTES:
            raise HomeAssistantError(f"Image at {url} is too large")
        return data

    def _async_store_token(self) -> None:
        token = self._frame.token
        if token and token != self._entry.data.get(CONF_TOKEN):
            self.hass.config_entries.async_update_entry(
                self._entry, data={**self._entry.data, CONF_TOKEN: token}
            )


def _prepare(data: bytes) -> tuple[bytes, bytes]:
    jpeg = fit_to_frame(data)
    return jpeg, make_preview(jpeg)
