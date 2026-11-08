"""Museum APIs that page with plain offsets (ported from RemArt's Dart sources)."""

import asyncio
from typing import Any, override

import aiohttp
from yarl import URL

from .base import ArtSource, Artwork, first, title_or_untitled

CC0 = "https://creativecommons.org/publicdomain/zero/1.0/"


class ChicagoSource(ArtSource):
    """Art Institute of Chicago."""

    source_id = "chicago"
    name = "Art Institute of Chicago"

    _base = "https://api.artic.edu/api/v1"
    _iiif = "https://lakeimagesweb.artic.edu/iiif/2"
    _fields = (
        "id",
        "title",
        "artist_display",
        "date_display",
        "image_id",
        "license_text",
    )

    @override
    async def fetch_page(self, page: int, page_size: int) -> list[Artwork]:
        body = await self._get_json(
            f"{self._base}/artworks/search",
            json={
                "query": {
                    "bool": {
                        "must": [
                            {"term": {"is_public_domain": True}},
                            {"exists": {"field": "image_id"}},
                        ]
                    }
                },
                "fields": list(self._fields),
                "page": page,
                "limit": page_size,
            },
        )
        return [a for e in body.get("data") or [] if (a := self._parse(e))]

    def _parse(self, e: dict[str, Any]) -> Artwork | None:
        if not (image_id := e.get("image_id")):
            return None
        return Artwork(
            id=str(e["id"]),
            source_id=self.source_id,
            image_url=f"{self._iiif}/{image_id}/full/1686,/0/default.jpg",
            thumb_url=f"{self._iiif}/{image_id}/full/400,/0/default.jpg",
            title=title_or_untitled(e.get("title")),
            artist=e.get("artist_display"),
            date=e.get("date_display"),
            license_text=e.get("license_text") or "Public Domain",
            license_url="https://www.artic.edu/terms",
        )


class MetSource(ArtSource):
    """The Metropolitan Museum of Art. Search returns ids, objects carry the data."""

    source_id = "met"
    name = "The Met"

    _base = "https://collectionapi.metmuseum.org/public/collection/v1"
    # v1/search was retired on 2026-10-01; v1.1 pages with offset/limit but
    # has no license filter. Most "painting" hits have no open image, but
    # the European Paintings department almost always does.
    _search = "https://collectionapi.metmuseum.org/public/collection/v1.1/search"
    _european_paintings = 11

    # v1.1 only serves the first 10,000 results of a query.
    _max_results = 10000

    @override
    async def fetch_page(self, page: int, page_size: int) -> list[Artwork]:
        offset = (page - 1) * page_size
        if offset >= self._max_results:
            return []
        body = await self._get_json(
            self._search,
            {
                "q": "*",
                "departmentId": self._european_paintings,
                "hasImages": "true",
                "offset": offset,
                "limit": min(page_size, self._max_results - offset),
            },
        )
        ids = body.get("objectIDs") or []
        artworks: list[Artwork] = []
        # Batches of 5 to stay polite with the API.
        for i in range(0, len(ids), 5):
            batch = await asyncio.gather(
                *(self._fetch_object(o) for o in ids[i : i + 5])
            )
            artworks.extend(a for a in batch if a)
        return artworks

    async def _fetch_object(self, object_id: int) -> Artwork | None:
        try:
            e = await self._get_json(f"{self._base}/objects/{object_id}")
        except aiohttp.ClientError, TimeoutError:
            return None
        if not (image_url := e.get("primaryImage")):
            return None
        # The v1.1 search cannot filter by license, so check it here.
        if e.get("isPublicDomain") is not True:
            return None
        # The department also holds empty picture frames.
        if e.get("classification") == "Frames":
            return None
        return Artwork(
            id=str(object_id),
            source_id=self.source_id,
            image_url=image_url,
            thumb_url=e.get("primaryImageSmall") or None,
            title=title_or_untitled(e.get("title")),
            artist=e.get("artistDisplayName") or None,
            date=e.get("objectDate") or None,
            license_text="CC0 Public Domain",
            license_url=CC0,
        )


class ClevelandSource(ArtSource):
    """Cleveland Museum of Art."""

    source_id = "cleveland"
    name = "Cleveland Museum of Art"

    _base = "https://openaccess-api.clevelandart.org/api/artworks/"

    @override
    async def fetch_page(self, page: int, page_size: int) -> list[Artwork]:
        body = await self._get_json(
            self._base,
            {
                "has_image": 1,
                "cc0": 1,
                "limit": page_size,
                "skip": (page - 1) * page_size,
            },
        )
        return [a for e in body.get("data") or [] if (a := self._parse(e))]

    def _parse(self, e: dict[str, Any]) -> Artwork | None:
        images = e.get("images") or {}
        if not (image_url := (images.get("web") or {}).get("url")):
            return None
        creator = first(e.get("creators")) or {}
        return Artwork(
            id=str(e["id"]),
            source_id=self.source_id,
            image_url=image_url,
            thumb_url=(images.get("print") or {}).get("url"),
            title=title_or_untitled(e.get("title")),
            artist=creator.get("description"),
            date=e.get("creation_date"),
            license_text="CC0 Public Domain",
            license_url=CC0,
        )


class SmkSource(ArtSource):
    """Statens Museum for Kunst (Copenhagen)."""

    source_id = "smk"
    name = "SMK – National Gallery of Denmark"

    _base = "https://api.smk.dk/api/v1/art/search"

    @override
    async def fetch_page(self, page: int, page_size: int) -> list[Artwork]:
        body = await self._get_json(
            self._base,
            {
                "keys": "*",
                "filters": "[has_image:true],[public_domain:true]",
                "offset": (page - 1) * page_size,
                "rows": page_size,
                "lang": "en",
            },
        )
        return [a for e in body.get("items") or [] if (a := self._parse(e))]

    def _parse(self, e: dict[str, Any]) -> Artwork | None:
        if not (image_url := e.get("image_native")):
            return None
        return Artwork(
            id=str(e["object_number"]),
            source_id=self.source_id,
            image_url=image_url,
            thumb_url=e.get("image_thumbnail"),
            title=title_or_untitled((first(e.get("titles")) or {}).get("title")),
            artist=first(e.get("artist")),
            date=(first(e.get("production_date")) or {}).get("period"),
            license_text="CC BY",
            license_url="https://creativecommons.org/licenses/by/4.0/",
        )


class MiaSource(ArtSource):
    """Minneapolis Institute of Art."""

    source_id = "mia"
    name = "Minneapolis Institute of Art"

    # The "+" is part of the path and must not be re-encoded.
    _search = URL("https://search.artsmia.org/rights_type:Public+Domain", encoded=True)
    _image_base = "https://4.api.artsmia.org"

    @override
    async def fetch_page(self, page: int, page_size: int) -> list[Artwork]:
        body = await self._get_json(
            self._search.with_query(size=page_size, **{"from": (page - 1) * page_size})
        )
        hits = (body.get("hits") or {}).get("hits") or []
        return [a for e in hits if (a := self._parse(e))]

    def _parse(self, e: dict[str, Any]) -> Artwork | None:
        source = e.get("_source")
        if not source or source.get("image") != "valid":
            return None
        object_id = str(source.get("id") or e.get("_id") or "")
        if not object_id:
            return None
        return Artwork(
            id=object_id,
            source_id=self.source_id,
            image_url=f"{self._image_base}/800/{object_id}.jpg",
            thumb_url=f"{self._image_base}/400/{object_id}.jpg",
            title=title_or_untitled(source.get("title")),
            artist=source.get("artist") or None,
            date=source.get("dated") or None,
            license_text="Public Domain",
            license_url=CC0,
        )


class RijksSource(ArtSource):
    """Rijksmuseum (API key required)."""

    source_id = "rijks"
    name = "Rijksmuseum"
    requires_api_key = True

    _base = "https://www.rijksmuseum.nl/api/en/collection"

    @override
    async def fetch_page(self, page: int, page_size: int) -> list[Artwork]:
        if not self._api_key:
            return []
        body = await self._get_json(
            self._base,
            {
                "key": self._api_key,
                "p": page,
                "ps": page_size,
                "imgonly": "true",
                "hasimage": "true",
            },
        )
        return [a for e in body.get("artObjects") or [] if (a := self._parse(e))]

    def _parse(self, e: dict[str, Any]) -> Artwork | None:
        if not (image_url := (e.get("webImage") or {}).get("url")):
            return None
        return Artwork(
            id=str(e["objectNumber"]),
            source_id=self.source_id,
            image_url=image_url,
            thumb_url=(e.get("headerImage") or {}).get("url"),
            title=title_or_untitled(e.get("title")),
            artist=e.get("principalOrFirstMaker"),
            date=(e.get("dating") or {}).get("presentingDate"),
            license_text="Rijksmuseum Collection",
            license_url="https://www.rijksmuseum.nl/en/terms-and-conditions",
        )


class EuropeanaSource(ArtSource):
    """Europeana (API key required)."""

    source_id = "europeana"
    name = "Europeana"
    requires_api_key = True

    _base = "https://api.europeana.eu/record/v2/search.json"

    @override
    async def fetch_page(self, page: int, page_size: int) -> list[Artwork]:
        if not self._api_key:
            return []
        body = await self._get_json(
            self._base,
            [
                ("wskey", self._api_key),
                ("query", "painting"),
                ("qf", "TYPE:IMAGE"),
                ("qf", "RIGHTS:*open*"),
                ("rows", page_size),
                ("start", (page - 1) * page_size + 1),
                ("profile", "rich"),
            ],
        )
        return [a for e in body.get("items") or [] if (a := self._parse(e))]

    def _parse(self, e: dict[str, Any]) -> Artwork | None:
        if not (image_url := first(e.get("edmIsShownBy"))):
            return None
        license_url = first(e.get("rights"))
        return Artwork(
            id=str(e["id"]),
            source_id=self.source_id,
            image_url=image_url,
            thumb_url=first(e.get("edmPreview")),
            title=title_or_untitled(first(e.get("title"))),
            artist=first(e.get("dcCreator")),
            date=first(e.get("year")),
            license_text=_license_label(license_url),
            license_url=license_url,
        )


def _license_label(url: str | None) -> str:
    if url is None:
        return "Open Access"
    if "publicdomain/zero" in url:
        return "CC0"
    if "publicdomain/mark" in url:
        return "Public Domain"
    if "by-sa" in url:
        return "CC BY-SA"
    if "/by/" in url:
        return "CC BY"
    return "Open Access"


class SmithsonianSource(ArtSource):
    """Smithsonian Open Access (api.data.gov key required)."""

    source_id = "smithsonian"
    name = "Smithsonian"
    requires_api_key = True

    _base = "https://api.si.edu/openaccess/api/v1.0/search"

    @override
    async def fetch_page(self, page: int, page_size: int) -> list[Artwork]:
        if not self._api_key:
            return []
        body = await self._get_json(
            self._base,
            {
                "q": "painting",
                "api_key": self._api_key,
                "rows": page_size,
                "start": (page - 1) * page_size,
                "online_media_type": "Images",
            },
        )
        rows = (body.get("response") or {}).get("rows") or []
        return [a for e in rows if (a := self._parse(e))]

    def _parse(self, e: dict[str, Any]) -> Artwork | None:
        content = e.get("content") or {}
        dnr = content.get("descriptiveNonRepeating") or {}
        media = next(
            (
                m
                for m in (dnr.get("online_media") or {}).get("media") or []
                if isinstance(m, dict) and m.get("type") == "Images"
            ),
            None,
        )
        if not media or not (image_url := media.get("content")):
            return None
        freetext = content.get("freetext") or {}
        creator = next(
            (
                n
                for n in freetext.get("name") or []
                if isinstance(n, dict) and n.get("label") == "Creator"
            ),
            {},
        )
        return Artwork(
            id=str(e["id"]),
            source_id=self.source_id,
            image_url=image_url,
            thumb_url=media.get("thumbnail"),
            title=title_or_untitled(
                (dnr.get("title") or {}).get("content") or e.get("title")
            ),
            artist=creator.get("content"),
            date=(first(freetext.get("date")) or {}).get("content"),
            license_text="CC0 Public Domain",
            license_url=CC0,
        )
