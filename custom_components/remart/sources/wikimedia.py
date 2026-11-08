"""Wikimedia Commons "Category:Paintings"."""

import re
from typing import Any, override

import aiohttp

from .base import ArtSource, Artwork

_RASTER_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp")
_WIDTH_PREFIX = re.compile(r"/\d+px-")
# Characters that appear unencoded in Commons file URLs but are invalid in a URI.
_URL_FIXES = str.maketrans(
    {'"': "%22", " ": "%20", "'": "%27", "(": "%28", ")": "%29", ",": "%2C"}
)


class WikimediaSource(ArtSource):
    """Wikimedia Commons. Pages with continue tokens, so only sequentially."""

    source_id = "wikimedia"
    name = "Wikimedia Commons"

    _api = "https://commons.wikimedia.org/w/api.php"
    _category = "Category:Paintings"

    def __init__(self, session: aiohttp.ClientSession, api_key: str | None = None):
        """Initialize the source."""
        super().__init__(session, api_key)
        self._continue_tokens: dict[int, str | None] = {1: None}

    @override
    async def fetch_page(self, page: int, page_size: int) -> list[Artwork]:
        if page not in self._continue_tokens:
            return []
        params: dict[str, Any] = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": self._category,
            "cmtype": "file",
            "cmlimit": page_size,
            "format": "json",
        }
        if token := self._continue_tokens[page]:
            params["cmcontinue"] = token
        body = await self._get_json(self._api, params)
        members = (body.get("query") or {}).get("categorymembers") or []
        if not members:
            return []
        if next_token := (body.get("continue") or {}).get("cmcontinue"):
            self._continue_tokens[page + 1] = next_token

        info = await self._get_json(
            self._api,
            {
                "action": "query",
                "pageids": "|".join(str(m["pageid"]) for m in members),
                "prop": "imageinfo|info",
                "iiprop": "url|extmetadata",
                "iiurlwidth": 1600,
                "format": "json",
            },
        )
        pages = (info.get("query") or {}).get("pages") or {}
        return [a for p in pages.values() if (a := self._parse(p))]

    def _parse(self, page: dict[str, Any]) -> Artwork | None:
        info = (page.get("imageinfo") or [None])[0]
        if not info:
            return None
        original = info.get("url")
        thumb = info.get("thumburl")
        original = original.translate(_URL_FIXES) if original else None
        thumb = thumb.translate(_URL_FIXES) if thumb else None
        # thumburl is always raster; the original may be SVG/TIFF/PDF.
        image_url = thumb or (
            original
            if original and original.lower().split("?")[0].endswith(_RASTER_EXTENSIONS)
            else None
        )
        if not image_url:
            return None

        meta = info.get("extmetadata") or {}

        def value(key: str) -> str | None:
            return (meta.get(key) or {}).get("value") or None

        title = value("ObjectName") or (page.get("title") or "Untitled").removeprefix(
            "File:"
        )
        return Artwork(
            id=str(page["pageid"]),
            source_id=self.source_id,
            image_url=image_url,
            thumb_url=_WIDTH_PREFIX.sub("/400px-", thumb, count=1)
            if thumb
            else image_url,
            title=title,
            artist=_strip_html(value("Artist")),
            date=_strip_html(value("DateTimeOriginal")),
            license_text=value("LicenseShortName") or "Public Domain",
            license_url=value("LicenseUrl"),
        )


_TAGS = re.compile(r"<[^>]+>")


def _strip_html(value: str | None) -> str | None:
    """Commons metadata is HTML; keep the text only."""
    if value is None:
        return None
    return " ".join(_TAGS.sub(" ", value).split()) or None
