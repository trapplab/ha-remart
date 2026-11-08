"""Stock photo libraries, searched with the configured terms."""

import contextlib
from typing import Any, override

import aiohttp
from yarl import URL

from .base import ArtSource, Artwork, title_or_untitled

DEFAULT_QUERY = "landscape"


class PixabaySource(ArtSource):
    """Pixabay. The key goes into the query string."""

    source_id = "pixabay"
    name = "Pixabay"
    requires_api_key = True
    searchable = True

    _api = "https://pixabay.com/api/"
    # The API serves at most 500 hits per query.
    _max_results = 500

    @override
    async def fetch_page(self, page: int, page_size: int) -> list[Artwork]:
        if not self._api_key:
            return []
        per_page = max(3, min(page_size, 200))
        if (page - 1) * per_page >= self._max_results:
            return []
        body = await self._get_json(
            self._api,
            {
                "key": self._api_key,
                "q": (self._query or DEFAULT_QUERY)[:100],
                "image_type": "photo",
                "orientation": "horizontal",
                "safesearch": "true",
                "order": "popular",
                "min_width": 1920,
                "per_page": per_page,
                "page": page,
            },
        )
        return [a for h in body.get("hits") or [] if (a := self._parse(h))]

    def _parse(self, h: dict[str, Any]) -> Artwork | None:
        # fullHDURL and imageURL need full API access; largeImageURL is 1280 px.
        image_url = h.get("fullHDURL") or h.get("largeImageURL")
        if not image_url:
            return None
        tags = [t.strip() for t in (h.get("tags") or "").split(",") if t.strip()]
        return Artwork(
            id=str(h["id"]),
            source_id=self.source_id,
            image_url=image_url,
            thumb_url=h.get("webformatURL") or h.get("previewURL"),
            title=", ".join(tags[:3]).capitalize() if tags else "Untitled",
            artist=h.get("user") or None,
            license_text="Pixabay Content License",
            license_url="https://pixabay.com/service/license-summary/",
        )


class UnsplashSource(ArtSource):
    """Unsplash. Shown photos are reported back, as the API guidelines ask."""

    source_id = "unsplash"
    name = "Unsplash"
    requires_api_key = True
    searchable = True

    _api = "https://api.unsplash.com"
    # Frame panels are at most 4K.
    _width = 3840

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Client-ID {self._api_key}", "Accept-Version": "v1"}

    @override
    async def fetch_page(self, page: int, page_size: int) -> list[Artwork]:
        if not self._api_key:
            return []
        body = await self._get_json(
            f"{self._api}/search/photos",
            {
                "query": self._query or DEFAULT_QUERY,
                "orientation": "landscape",
                "content_filter": "high",
                "per_page": min(page_size, 30),
                "page": page,
            },
            headers=self._headers(),
        )
        if page > (body.get("total_pages") or 0):
            return []
        return [a for p in body.get("results") or [] if (a := self._parse(p))]

    def _parse(self, p: dict[str, Any]) -> Artwork | None:
        urls = p.get("urls") or {}
        if raw := urls.get("raw"):
            image_url = str(
                URL(raw).update_query(w=self._width, fm="jpg", q=85, fit="max")
            )
        elif not (image_url := urls.get("full")):
            return None
        user = p.get("user") or {}
        return Artwork(
            id=str(p["id"]),
            source_id=self.source_id,
            image_url=image_url,
            thumb_url=urls.get("small") or urls.get("thumb"),
            title=title_or_untitled(p.get("description") or p.get("alt_description")),
            artist=user.get("name") or None,
            date=(p.get("created_at") or "")[:10] or None,
            license_text="Unsplash License",
            license_url="https://unsplash.com/license",
            track_url=(p.get("links") or {}).get("download_location"),
        )

    @override
    async def async_track_use(self, artwork: Artwork) -> None:
        if not artwork.track_url or not self._api_key:
            return
        with contextlib.suppress(aiohttp.ClientError, TimeoutError):
            await self._get_json(artwork.track_url, headers=self._headers())
