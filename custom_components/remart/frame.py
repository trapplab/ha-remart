"""Talk to the Samsung Frame's art channel."""

import asyncio
from dataclasses import dataclass
import logging
import time

from samsungtvws.art import SamsungTVArt
from samsungtvws.exceptions import ConnectionFailure, ResponseError
from websocket import WebSocketException

from homeassistant.core import HomeAssistant

from .const import CLIENT_NAME, MY_PICTURES_CATEGORY

_LOGGER = logging.getLogger(__name__)

# Uploads of 4K JPEGs over the D2D socket can take a while.
UPLOAD_TIMEOUT = 30
# Some firmwares never answer set_artmode_status / select_image.
ACK_TIMEOUT = 5
# Without this pause the TV can still show the previous image.
INDEX_DELAY = 0.8


class FrameError(Exception):
    """Raised when the Frame cannot be reached or rejects a request."""


class NotAFrameError(FrameError):
    """Raised when the TV does not support art mode."""


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
                art.select_image(content_id, category=MY_PICTURES_CATEGORY, show=True)
            except ConnectionFailure, ResponseError:
                # Some firmwares never answer but show the new upload anyway.
                _LOGGER.debug("No ACK for select_image, continuing")
        except (ConnectionFailure, OSError, WebSocketException) as err:
            raise FrameError(f"Frame at {self.host} failed: {err}") from err
        except ResponseError as err:
            raise FrameError(f"Frame at {self.host} rejected the image: {err}") from err
        finally:
            art.close()
        if art.token:
            self.token = art.token
        return content_id
