"""Common types for art sources."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar

import aiohttp
from yarl import URL

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=20)
USER_AGENT = "HomeAssistant-RemArt/0.1 (+https://github.com/trapplab/ha-remart)"


@dataclass(frozen=True, slots=True)
class Artwork:
    """One artwork from a museum source."""

    id: str
    source_id: str
    image_url: str
    thumb_url: str | None
    title: str
    artist: str | None = None
    date: str | None = None
    license_text: str = "Public Domain"
    license_url: str | None = None


class ArtSource(ABC):
    """A paged collection of public-domain artworks."""

    source_id: ClassVar[str]
    name: ClassVar[str]
    requires_api_key: ClassVar[bool] = False

    def __init__(self, session: aiohttp.ClientSession, api_key: str | None = None):
        """Initialize the source."""
        self._session = session
        self._api_key = api_key

    @abstractmethod
    async def fetch_page(self, page: int, page_size: int) -> list[Artwork]:
        """Return a 1-based page of artworks, or [] when there are no more."""

    async def _get_json(
        self, url: str | URL, params: Any = None, *, json: Any = None
    ) -> Any:
        method = "POST" if json is not None else "GET"
        async with self._session.request(
            method,
            url,
            params=params,
            json=json,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        ) as resp:
            resp.raise_for_status()
            return await resp.json(content_type=None)


def first(value: Any) -> Any:
    """Return the first element of a list, or None."""
    if isinstance(value, list) and value:
        return value[0]
    return None


def title_or_untitled(value: Any) -> str:
    """Return a non-empty title."""
    return value if isinstance(value, str) and value else "Untitled"
