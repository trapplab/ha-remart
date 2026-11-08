"""Browse the museum sources in Home Assistant's media browser.

Identifiers: "" (root) → "<source>" → "<source>/<page>" → "<source>/<page>/<artwork id>".
Artwork ids are URL-quoted because some (Europeana) contain slashes.
"""

from dataclasses import dataclass
from urllib.parse import quote, unquote

from homeassistant.components.media_player import BrowseError, MediaClass
from homeassistant.components.media_source import (
    BrowseMediaSource,
    MediaSource,
    MediaSourceItem,
    PlayMedia,
    Unresolvable,
)
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .gallery import Gallery
from .sources import Artwork

IMAGE_MIME = "image/jpeg"


@dataclass(frozen=True, slots=True)
class Identifier:
    """A parsed media source identifier."""

    source_id: str | None = None
    page: int = 1
    artwork_id: str | None = None


def parse_identifier(identifier: str) -> Identifier:
    """Split an identifier into source, page and artwork."""
    if not identifier:
        return Identifier()
    source_id, _, rest = identifier.partition("/")
    page_str, _, artwork = rest.partition("/")
    try:
        page = int(page_str) if page_str else 1
    except ValueError as err:
        raise BrowseError(f"Invalid page in {identifier}") from err
    return Identifier(source_id, page, unquote(artwork) if artwork else None)


def artwork_identifier(artwork: Artwork, page: int) -> str:
    """Build the identifier of an artwork on a page."""
    return f"{artwork.source_id}/{page}/{quote(artwork.id, safe='')}"


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

    async def async_resolve_media(self, item: MediaSourceItem) -> PlayMedia:
        """Resolve an artwork to its full-size image URL."""
        parsed = parse_identifier(item.identifier)
        if parsed.source_id is None or parsed.artwork_id is None:
            raise Unresolvable(f"Not an artwork: {item.identifier}")
        artwork = await self._gallery().async_get_artwork(
            parsed.source_id, parsed.page, parsed.artwork_id
        )
        if artwork is None:
            raise Unresolvable(f"Artwork not found: {item.identifier}")
        return PlayMedia(artwork.image_url, IMAGE_MIME)

    async def async_browse_media(self, item: MediaSourceItem) -> BrowseMediaSource:
        """Browse sources, pages and artworks."""
        gallery = self._gallery()
        parsed = parse_identifier(item.identifier)

        if parsed.source_id is None:
            return self._directory(
                "",
                "RemArt",
                [
                    self._directory(source_id, source.name)
                    for source_id, source in gallery.sources.items()
                ],
            )

        source = gallery.sources.get(parsed.source_id)
        if source is None:
            raise BrowseError(f"Unknown source: {parsed.source_id}")

        artworks = await gallery.async_get_page(parsed.source_id, parsed.page)
        if parsed.artwork_id is not None:
            for artwork in artworks:
                if artwork.id == parsed.artwork_id:
                    return self._artwork(artwork, parsed.page)
            raise BrowseError(f"Artwork not found: {item.identifier}")

        children = [self._artwork(artwork, parsed.page) for artwork in artworks]
        # A short page is the last one; sources may drop items without an image,
        # so any non-empty page may still be followed by another.
        if artworks:
            next_page = parsed.page + 1
            children.append(
                self._directory(
                    f"{parsed.source_id}/{next_page}",
                    f"{self._page_label()} {next_page} →",
                )
            )
        title = source.name
        if parsed.page > 1:
            title = f"{source.name} – {self._page_label()} {parsed.page}"
        return self._directory(f"{parsed.source_id}/{parsed.page}", title, children)

    def _page_label(self) -> str:
        return "Seite" if self.hass.config.language.startswith("de") else "Page"

    def _directory(
        self,
        identifier: str,
        title: str,
        children: list[BrowseMediaSource] | None = None,
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
        )

    def _artwork(self, artwork: Artwork, page: int) -> BrowseMediaSource:
        title = (
            f"{artwork.title} – {artwork.artist}" if artwork.artist else artwork.title
        )
        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=artwork_identifier(artwork, page),
            media_class=MediaClass.IMAGE,
            media_content_type=IMAGE_MIME,
            title=title,
            can_play=True,
            can_expand=False,
            thumbnail=artwork.thumb_url or artwork.image_url,
        )
