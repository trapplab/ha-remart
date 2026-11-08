"""Browse the art sources and the Frames' stored images in the media browser.

Identifiers: "" (root) → "<source>" → "<source>/<page>" → "<source>/<page>/<artwork id>".
Artwork ids are URL-quoted because some (Europeana) contain slashes.
Searches in a photo library: "<source>@<query>/<page>/<artwork id>", query URL-quoted.
Images on a Frame: "on_frame/<entry id>" → "on_frame/<entry id>/<content id>".
"""

from dataclasses import dataclass
from urllib.parse import quote, unquote

import aiohttp

from homeassistant.components.media_player import (
    BrowseError,
    MediaClass,
    SearchMedia,
    SearchMediaQuery,
)
from homeassistant.components.media_source import (
    BrowseMediaSource,
    MediaSource,
    MediaSourceItem,
    PlayMedia,
    Unresolvable,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from .catalog import FrameArt
from .const import DOMAIN
from .frame import FrameError
from .gallery import Gallery
from .models import RemArtConfigEntry
from .sources import Artwork

IMAGE_MIME = "image/jpeg"
ON_FRAME = "on_frame"


@dataclass(frozen=True, slots=True)
class Identifier:
    """A parsed media source identifier."""

    source_id: str | None = None
    page: int = 1
    artwork_id: str | None = None
    query: str | None = None


def parse_identifier(identifier: str) -> Identifier:
    """Split an identifier into source, page, artwork and search query."""
    if not identifier:
        return Identifier()
    source_part, _, rest = identifier.partition("/")
    source_id, _, query = source_part.partition("@")
    page_str, _, artwork = rest.partition("/")
    try:
        page = int(page_str) if page_str else 1
    except ValueError as err:
        raise BrowseError(f"Invalid page in {identifier}") from err
    return Identifier(
        source_id,
        page,
        unquote(artwork) if artwork else None,
        unquote(query).strip() or None,
    )


def page_identifier(source_id: str, page: int, query: str | None = None) -> str:
    """Build the identifier of a page of a source or of a search in it."""
    if query:
        return f"{source_id}@{quote(query, safe='')}/{page}"
    return f"{source_id}/{page}"


def artwork_identifier(artwork: Artwork, page: int, query: str | None = None) -> str:
    """Build the identifier of an artwork on a page."""
    return (
        f"{page_identifier(artwork.source_id, page, query)}/"
        f"{quote(artwork.id, safe='')}"
    )


def frame_identifier(entry_id: str, content_id: str | None = None) -> str:
    """Build the identifier of a Frame's stored images or one of them."""
    if content_id is None:
        return f"{ON_FRAME}/{entry_id}"
    return f"{ON_FRAME}/{entry_id}/{quote(content_id, safe='')}"


def parse_frame_identifier(
    identifier: str | None,
) -> tuple[str, str | None] | None:
    """Return (entry id, content id) for stored images, None for the gallery."""
    if not identifier:
        return None
    prefix, _, rest = identifier.partition("/")
    if prefix != ON_FRAME or not rest:
        return None
    entry_id, _, content_id = rest.partition("/")
    return entry_id, unquote(content_id) if content_id else None


def thumbnail_url(entry_id: str, content_id: str) -> str:
    """Return the URL serving a stored image's thumbnail from the TV."""
    return f"/api/{DOMAIN}/{entry_id}/thumbnail/{quote(content_id, safe='')}"


async def async_get_media_source(hass: HomeAssistant) -> RemArtMediaSource:
    """Set up the RemArt media source."""
    return RemArtMediaSource(hass)


class RemArtMediaSource(MediaSource):
    """Public-domain artworks from museum APIs."""

    name = "RemArt"

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the media source."""
        super().__init__(DOMAIN)
        self.hass = hass

    def _gallery(self) -> Gallery:
        entries = self.hass.config_entries.async_loaded_entries(DOMAIN)
        if not entries:
            raise Unresolvable("RemArt is not set up")
        return entries[0].runtime_data.gallery

    def _entry(self, entry_id: str) -> RemArtConfigEntry:
        entry = self.hass.config_entries.async_get_entry(entry_id)
        if (
            entry is None
            or entry.domain != DOMAIN
            or entry.state is not ConfigEntryState.LOADED
        ):
            raise Unresolvable(f"Frame not set up: {entry_id}")
        return entry

    async def async_resolve_media(self, item: MediaSourceItem) -> PlayMedia:
        """Resolve an artwork to its full-size image URL.

        Images stored on a Frame resolve to their thumbnail; the Frame itself
        selects them without a download.
        """
        if stored := parse_frame_identifier(item.identifier):
            entry_id, content_id = stored
            if content_id is None:
                raise Unresolvable(f"Not an image: {item.identifier}")
            self._entry(entry_id)
            return PlayMedia(thumbnail_url(entry_id, content_id), IMAGE_MIME)
        parsed = parse_identifier(item.identifier)
        if parsed.source_id is None or parsed.artwork_id is None:
            raise Unresolvable(f"Not an artwork: {item.identifier}")
        artwork = await self._gallery().async_get_artwork(
            parsed.source_id, parsed.page, parsed.artwork_id, parsed.query
        )
        if artwork is None:
            raise Unresolvable(f"Artwork not found: {item.identifier}")
        return PlayMedia(artwork.image_url, IMAGE_MIME)

    async def async_browse_media(self, item: MediaSourceItem) -> BrowseMediaSource:
        """Browse sources, pages and artworks."""
        if stored := parse_frame_identifier(item.identifier):
            return await self._async_browse_frame(*stored)

        gallery = self._gallery()
        parsed = parse_identifier(item.identifier)

        if parsed.source_id is None:
            entries = self.hass.config_entries.async_loaded_entries(DOMAIN)
            return self._directory(
                "",
                "RemArt",
                [
                    self._directory(
                        frame_identifier(entry.entry_id),
                        self._on_frame_label(entry, len(entries) > 1),
                    )
                    for entry in entries
                ]
                + [
                    self._directory(
                        source_id, source.name, can_search=source.searchable
                    )
                    for source_id, source in gallery.sources.items()
                ],
            )

        source = gallery.sources.get(parsed.source_id)
        if source is None:
            raise BrowseError(f"Unknown source: {parsed.source_id}")

        if parsed.query and not source.searchable:
            raise BrowseError(f"{source.name} cannot be searched")

        artworks = await gallery.async_get_page(
            parsed.source_id, parsed.page, parsed.query
        )
        if parsed.artwork_id is not None:
            for artwork in artworks:
                if artwork.id == parsed.artwork_id:
                    return self._artwork(artwork, parsed.page, parsed.query)
            raise BrowseError(f"Artwork not found: {item.identifier}")

        title = source.name
        if parsed.query:
            title = f"{title}: {parsed.query}"
        if parsed.page > 1:
            title = f"{title} – {self._page_label()} {parsed.page}"
        return self._directory(
            page_identifier(parsed.source_id, parsed.page, parsed.query),
            title,
            self._page_children(artworks, parsed.source_id, parsed.page, parsed.query),
            can_search=source.searchable,
        )

    async def async_search_media(
        self, item: MediaSourceItem, query: SearchMediaQuery
    ) -> SearchMedia:
        """Search a photo library on its website, not just the listed photos."""
        parsed = parse_identifier(item.identifier)
        if parsed.source_id is None or parse_frame_identifier(item.identifier):
            raise NotImplementedError
        gallery = self._gallery()
        source = gallery.sources.get(parsed.source_id)
        if source is None or not source.searchable:
            raise NotImplementedError
        search = query.search_query.strip()
        if not search or (
            query.media_filter_classes
            and MediaClass.IMAGE not in query.media_filter_classes
        ):
            return SearchMedia(result=[])
        try:
            artworks = await gallery.async_get_page(parsed.source_id, 1, search)
        except aiohttp.ClientResponseError as err:
            raise BrowseError(
                f"{source.name} search failed: {err.status} {err.message}"
            ) from err
        except (aiohttp.ClientError, TimeoutError) as err:
            raise BrowseError(f"{source.name} is not reachable: {err}") from err
        return SearchMedia(
            result=self._page_children(artworks, parsed.source_id, 1, search)
        )

    def _page_children(
        self,
        artworks: list[Artwork],
        source_id: str,
        page: int,
        query: str | None,
    ) -> list[BrowseMediaSource]:
        children = [self._artwork(artwork, page, query) for artwork in artworks]
        # A short page is the last one; sources may drop items without an image,
        # so any non-empty page may still be followed by another.
        if artworks:
            next_page = page + 1
            children.append(
                self._directory(
                    page_identifier(source_id, next_page, query),
                    f"{self._page_label()} {next_page} →",
                )
            )
        return children

    async def _async_browse_frame(
        self, entry_id: str, content_id: str | None
    ) -> BrowseMediaSource:
        try:
            entry = self._entry(entry_id)
        except Unresolvable as err:
            raise BrowseError(str(err)) from err
        data = entry.runtime_data
        try:
            items = await data.catalog.async_list(data.frame)
        except FrameError as err:
            raise BrowseError(str(err)) from err
        children = [self._stored(entry_id, art) for art in items]
        if content_id is not None:
            for child in children:
                if child.identifier == frame_identifier(entry_id, content_id):
                    return child
            raise BrowseError(f"Not on the Frame: {content_id}")
        return self._directory(
            frame_identifier(entry_id), self._on_frame_label(entry, True), children
        )

    def _german(self) -> bool:
        return self.hass.config.language.startswith("de")

    def _page_label(self) -> str:
        return "Seite" if self._german() else "Page"

    def _on_frame_label(self, entry: RemArtConfigEntry, with_name: bool) -> str:
        label = "Auf dem Frame" if self._german() else "On the Frame"
        return f"{label} – {entry.title}" if with_name else label

    def _stored(self, entry_id: str, art: FrameArt) -> BrowseMediaSource:
        title = art.title or art.content_id
        if art.artist:
            title = f"{title} – {art.artist}"
        if art.current:
            title = f"{title} ({'angezeigt' if self._german() else 'shown'})"
        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=frame_identifier(entry_id, art.content_id),
            media_class=MediaClass.IMAGE,
            media_content_type=IMAGE_MIME,
            title=title,
            can_play=True,
            can_expand=False,
            thumbnail=thumbnail_url(entry_id, art.content_id),
        )

    def _directory(
        self,
        identifier: str,
        title: str,
        children: list[BrowseMediaSource] | None = None,
        *,
        can_search: bool = False,
    ) -> BrowseMediaSource:
        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=identifier,
            media_class=MediaClass.DIRECTORY,
            media_content_type="",
            title=title,
            can_play=False,
            can_expand=True,
            children=children,
            children_media_class=MediaClass.IMAGE if children else None,
            can_search=can_search,
            search_media_classes=[MediaClass.IMAGE] if can_search else None,
        )

    def _artwork(
        self, artwork: Artwork, page: int, query: str | None = None
    ) -> BrowseMediaSource:
        title = (
            f"{artwork.title} – {artwork.artist}" if artwork.artist else artwork.title
        )
        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=artwork_identifier(artwork, page, query),
            media_class=MediaClass.IMAGE,
            media_content_type=IMAGE_MIME,
            title=title,
            can_play=True,
            can_expand=False,
            thumbnail=artwork.thumb_url or artwork.image_url,
        )
