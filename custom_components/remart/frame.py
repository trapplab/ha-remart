"""Talk to the Samsung Frame's art channel."""

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
import logging
import time

from samsungtvws.art import SamsungTVArt
from samsungtvws.exceptions import ConnectionFailure, ResponseError
from websocket import WebSocketException

from homeassistant.core import HomeAssistant

from .const import CLIENT_NAME, FAVORITES_CATEGORY, MY_PICTURES_CATEGORY

_LOGGER = logging.getLogger(__name__)

# Uploads of 4K JPEGs over the D2D socket can take a while.
UPLOAD_TIMEOUT = 30
# Some firmwares never answer set_artmode_status / select_image.
ACK_TIMEOUT = 5
# Without this pause the TV can still show the previous image.
INDEX_DELAY = 0.8
# Listing and thumbnails are small but slow on busy TVs.
QUERY_TIMEOUT = 15
# Thumbnails kept in memory per Frame (about 30 kB each).
THUMB_CACHE_SIZE = 300
# A media browser grid asks for its thumbnails within a few milliseconds;
# collect them into one request to the TV.
THUMB_BATCH_DELAY = 0.1
# Thumbnails fetched per turn; the lock is released in between so that
# selecting or uploading an image does not wait for a whole grid.
THUMB_BATCH_SIZE = 12


class FrameError(Exception):
    """Raised when the Frame cannot be reached or rejects a request."""


class NotAFrameError(FrameError):
    """Raised when the TV does not support art mode."""


@dataclass(frozen=True, slots=True)
class StoredArt:
    """An image in the Frame's "My Photos" category."""

    content_id: str
    date: str | None = None
    category: str | None = None

    @property
    def deletable(self) -> bool:
        """Only own uploads can be deleted; Samsung's art stays."""
        if self.category is None:
            return self.content_id.startswith("MY_F")
        return self.category == MY_PICTURES_CATEGORY


@dataclass(slots=True)
class DeviceInfo:
    """What the TV reports about itself."""

    unique_id: str
    model: str | None
    name: str | None


class FrameClient:
    """Uploads images to a Frame TV and shows them in art mode."""

    def __init__(self, host: str, port: int, token: str | None, matte: str) -> None:
        """Initialize the client."""
        self.host = host
        self.port = port
        self.token = token
        self.matte = matte
        self._lock = asyncio.Lock()
        self._thumbs: OrderedDict[str, bytes] = OrderedDict()
        self._thumb_waiters: dict[str, asyncio.Future[bytes | None]] = {}
        self._thumb_task: asyncio.Task[None] | None = None
        self._categories: dict[str, str] = {}

    def _art(self, timeout: float) -> SamsungTVArt:
        return SamsungTVArt(
            self.host,
            token=self.token,
            port=self.port,
            timeout=timeout,
            name=CLIENT_NAME,
        )

    def pair(self) -> DeviceInfo:
        """Check art support and open the art channel once to obtain a token.

        The TV shows an "allow" prompt on first contact. Blocking.
        """
        art = self._art(UPLOAD_TIMEOUT)
        try:
            info = art._get_rest_api().rest_device_info()
        except Exception as err:
            raise FrameError(f"Cannot reach TV at {self.host}: {err}") from err
        device = info.get("device") or {}
        if str(device.get("FrameTVSupport")).lower() != "true":
            raise NotAFrameError(f"{self.host} does not support Frame art mode")
        try:
            art.open()
        except (ConnectionFailure, OSError, WebSocketException) as err:
            raise FrameError(f"Art channel refused: {err}") from err
        finally:
            art.close()
        if art.token:
            self.token = art.token
        return DeviceInfo(
            unique_id=str(device.get("duid") or device.get("id") or self.host),
            model=device.get("modelName"),
            name=device.get("name"),
        )

    async def async_show(self, hass: HomeAssistant, jpeg: bytes) -> str:
        """Upload ``jpeg``, switch to art mode and display it.

        Returns the TV's content id. Uploads are serialized.
        """
        async with self._lock:
            return await hass.async_add_executor_job(self._show, jpeg)

    def _show(self, jpeg: bytes) -> str:
        art = self._art(UPLOAD_TIMEOUT)
        try:
            art.open()
            content_id = art.upload(
                jpeg, matte=self.matte, portrait_matte=self.matte, file_type="jpg"
            )
            _LOGGER.debug("Uploaded %d bytes as %s", len(jpeg), content_id)
            time.sleep(INDEX_DELAY)
            self._activate(art, content_id)
        except (ConnectionFailure, OSError, WebSocketException) as err:
            raise FrameError(f"Frame at {self.host} failed: {err}") from err
        except ResponseError as err:
            raise FrameError(f"Frame at {self.host} rejected the image: {err}") from err
        finally:
            art.close()
        if art.token:
            self.token = art.token
        return content_id

    async def async_list(
        self, hass: HomeAssistant
    ) -> tuple[list[StoredArt], str | None]:
        """Return the stored images, newest first, and the shown content id."""
        async with self._lock:
            return await hass.async_add_executor_job(self._list)

    def _list(self) -> tuple[list[StoredArt], str | None]:
        art = self._art(QUERY_TIMEOUT)
        try:
            art.open()
            # Without a category the TV lists everything it stores: own
            # uploads as well as Samsung's free and Art Store pictures.
            items = art.available()
            assert art.connection
            art.connection.settimeout(ACK_TIMEOUT)
            try:
                current = (art.get_current() or {}).get("content_id")
            except ConnectionFailure, ResponseError:
                current = None
        except (ConnectionFailure, OSError, WebSocketException) as err:
            raise FrameError(f"Frame at {self.host} failed: {err}") from err
        except (ResponseError, KeyError, TypeError, ValueError) as err:
            raise FrameError(f"Frame at {self.host} sent no art list: {err}") from err
        finally:
            art.close()
        by_id: dict[str, StoredArt] = {}
        for item in items or []:
            if not isinstance(item, dict) or not item.get("content_id"):
                continue
            content_id = str(item["content_id"])
            category = item.get("category_id") or None
            known = by_id.get(content_id)
            # Favourites show up a second time in their own category.
            if known is not None and known.category == MY_PICTURES_CATEGORY:
                continue
            if known is not None and category == FAVORITES_CATEGORY:
                continue
            by_id[content_id] = StoredArt(
                content_id, item.get("image_date") or None, category
            )
        self._categories = {
            art.content_id: art.category for art in by_id.values() if art.category
        }
        stored = list(by_id.values())
        stored.sort(key=lambda a: a.date or "", reverse=True)
        return stored, current

    def category(self, content_id: str) -> str | None:
        """Return the category of a stored image, as last listed."""
        if (category := self._categories.get(content_id)) is not None:
            return category
        if content_id.startswith("MY_F"):
            return MY_PICTURES_CATEGORY
        return None

    def deletable(self, content_id: str) -> bool:
        """Return whether a stored image is an own upload."""
        return self.category(content_id) == MY_PICTURES_CATEGORY

    async def async_select(self, hass: HomeAssistant, content_id: str) -> None:
        """Show an image that is already stored on the Frame."""
        async with self._lock:
            await hass.async_add_executor_job(self._select, content_id)

    def _select(self, content_id: str) -> None:
        art = self._art(QUERY_TIMEOUT)
        try:
            art.open()
            self._activate(art, content_id, self.category(content_id))
        except (ConnectionFailure, OSError, WebSocketException) as err:
            raise FrameError(f"Frame at {self.host} failed: {err}") from err
        finally:
            art.close()

    async def async_delete(self, hass: HomeAssistant, content_id: str) -> None:
        """Delete an image from the Frame's "My Photos"."""
        async with self._lock:
            await hass.async_add_executor_job(self._delete, content_id)
        self._thumbs.pop(content_id, None)

    def _delete(self, content_id: str) -> None:
        art = self._art(QUERY_TIMEOUT)
        try:
            art.open()
            deleted = art.delete(content_id)
        except (ConnectionFailure, OSError, WebSocketException) as err:
            raise FrameError(f"Frame at {self.host} failed: {err}") from err
        except ResponseError as err:
            raise FrameError(
                f"Frame at {self.host} did not delete {content_id}: {err}"
            ) from err
        finally:
            art.close()
        if not deleted:
            raise FrameError(f"Frame at {self.host} did not delete {content_id}")

    def _activate(
        self,
        art: SamsungTVArt,
        content_id: str,
        category: str | None = MY_PICTURES_CATEGORY,
    ) -> None:
        """Switch to art mode and show ``content_id`` on an open connection."""
        assert art.connection
        art.connection.settimeout(ACK_TIMEOUT)
        # The TV does not answer set_artmode_status when art mode is
        # already on, so ask first.
        try:
            mode = art.get_artmode()
        except ConnectionFailure, ResponseError:
            mode = None
        if mode != "on":
            try:
                art.set_artmode("on")
            except ConnectionFailure, ResponseError:
                _LOGGER.debug("No ACK for set_artmode, continuing")
        try:
            art.select_image(content_id, category=category, show=True)
        except ConnectionFailure, ResponseError:
            # Some firmwares never answer but show the image anyway.
            _LOGGER.debug("No ACK for select_image, continuing")

    def cached_thumbnail(self, content_id: str) -> bytes | None:
        """Return a thumbnail without asking the TV."""
        return self._thumbs.get(content_id)

    def cache_thumbnail(self, content_id: str, jpeg: bytes) -> None:
        """Remember a thumbnail, e.g. the preview of a fresh upload."""
        self._thumbs[content_id] = jpeg
        self._thumbs.move_to_end(content_id)
        while len(self._thumbs) > THUMB_CACHE_SIZE:
            self._thumbs.popitem(last=False)

    async def async_thumbnail(
        self, hass: HomeAssistant, content_id: str
    ) -> bytes | None:
        """Return a thumbnail of a stored image, or None if the TV has none.

        Requests arriving while the TV is busy are fetched together over one
        connection, so a grid of thumbnails does not open a socket per image.
        """
        if (cached := self._thumbs.get(content_id)) is not None:
            return cached
        future = self._thumb_waiters.get(content_id)
        if future is None:
            future = hass.loop.create_future()
            self._thumb_waiters[content_id] = future
            if self._thumb_task is None or self._thumb_task.done():
                self._thumb_task = hass.async_create_background_task(
                    self._async_fetch_thumbnails(hass), "remart thumbnails"
                )
        return await asyncio.shield(future)

    async def _async_fetch_thumbnails(self, hass: HomeAssistant) -> None:
        while self._thumb_waiters:
            await asyncio.sleep(THUMB_BATCH_DELAY)
            async with self._lock:
                batch = dict(list(self._thumb_waiters.items())[:THUMB_BATCH_SIZE])
                for content_id in batch:
                    del self._thumb_waiters[content_id]
                try:
                    found = await hass.async_add_executor_job(
                        self._thumbnails, list(batch)
                    )
                except FrameError as err:
                    _LOGGER.debug("Thumbnails failed: %s", err)
                    found = {}
            for content_id, future in batch.items():
                data = found.get(content_id)
                if data is not None:
                    self.cache_thumbnail(content_id, data)
                if not future.done():
                    future.set_result(data)

    def _thumbnails(self, content_ids: list[str]) -> dict[str, bytes]:
        art = self._art(QUERY_TIMEOUT)
        found: dict[str, bytes] = {}
        try:
            art.open()
            for content_id in content_ids:
                try:
                    data = art.get_thumbnail(content_id)
                except ResponseError as err:
                    _LOGGER.debug("No thumbnail for %s: %s", content_id, err)
                    continue
                if isinstance(data, (bytes, bytearray)) and data:
                    found[content_id] = bytes(data)
        except (ConnectionFailure, OSError, WebSocketException) as err:
            if not found:
                raise FrameError(f"Frame at {self.host} failed: {err}") from err
            _LOGGER.debug("Thumbnail batch cut short: %s", err)
        finally:
            art.close()
        return found
