"""Paged, cached access to the enabled art sources."""

import time

import aiohttp

from .const import PAGE_CACHE_TTL, PAGE_SIZE
from .sources import SOURCES, ArtSource, Artwork


class Gallery:
    """Holds the enabled sources and caches their pages.

    The cache lets the media browser resolve an artwork it listed earlier
    without asking the museum again.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        enabled: list[str],
        api_keys: dict[str, str],
        query: str | None = None,
    ) -> None:
        """Initialize the gallery."""
        self.sources: dict[str, ArtSource] = {}
        for source_id in enabled:
            cls = SOURCES.get(source_id)
            if cls is None:
                continue
            key = api_keys.get(source_id) or None
            if cls.requires_api_key and not key:
                continue
            self.sources[source_id] = cls(session, key, query)
        self._pages: dict[tuple[str, int], tuple[float, list[Artwork]]] = {}

    async def async_get_page(self, source_id: str, page: int) -> list[Artwork]:
        """Return a page of a source, from cache when fresh."""
        source = self.sources.get(source_id)
        if source is None or page < 1:
            return []
        now = time.monotonic()
        cached = self._pages.get((source_id, page))
        if cached and now - cached[0] < PAGE_CACHE_TTL:
            return cached[1]
        artworks = await source.fetch_page(page, PAGE_SIZE)
        self._pages[(source_id, page)] = (now, artworks)
        return artworks

    async def async_get_artwork(
        self, source_id: str, page: int, artwork_id: str
    ) -> Artwork | None:
        """Find an artwork on a page."""
        for artwork in await self.async_get_page(source_id, page):
            if artwork.id == artwork_id:
                return artwork
        return None

    async def async_track_use(self, artwork: Artwork) -> None:
        """Report a shown artwork to its source."""
        if source := self.sources.get(artwork.source_id):
            await source.async_track_use(artwork)
