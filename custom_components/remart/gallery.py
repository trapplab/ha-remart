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
        self._pages: dict[tuple[str, int, str | None], tuple[float, list[Artwork]]] = {}

    async def async_get_page(
        self, source_id: str, page: int, query: str | None = None
    ) -> list[Artwork]:
        """Return a page of a source, or of a search in it, from cache when fresh."""
        source = self.sources.get(source_id)
        if source is None or page < 1 or (query and not source.searchable):
            return []
        now = time.monotonic()
        key = (source_id, page, query or None)
        cached = self._pages.get(key)
        if cached and now - cached[0] < PAGE_CACHE_TTL:
            return cached[1]
        if query:
            artworks = await source.search_page(query, page, PAGE_SIZE)
        else:
            artworks = await source.fetch_page(page, PAGE_SIZE)
        # Searches add new keys, so drop what has expired.
        self._pages = {
            k: v for k, v in self._pages.items() if now - v[0] < PAGE_CACHE_TTL
        }
        self._pages[key] = (now, artworks)
        return artworks

    async def async_get_artwork(
        self, source_id: str, page: int, artwork_id: str, query: str | None = None
    ) -> Artwork | None:
        """Find an artwork on a page."""
        for artwork in await self.async_get_page(source_id, page, query):
            if artwork.id == artwork_id:
                return artwork
        return None

    async def async_track_use(self, artwork: Artwork) -> None:
        """Report a shown artwork to its source."""
        if source := self.sources.get(artwork.source_id):
            await source.async_track_use(artwork)
