"""Titles of the images uploaded to a Frame.

The TV only knows content ids, so what was uploaded is remembered here.
"""

from dataclasses import dataclass
from typing import TypedDict

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .frame import FrameClient

SAVE_DELAY = 5


class CatalogItem(TypedDict):
    """What is known about an uploaded image."""

    title: str | None
    artist: str | None


@dataclass(frozen=True, slots=True)
class FrameArt:
    """An image on the Frame with what is known about it."""

    content_id: str
    title: str | None
    artist: str | None
    current: bool
    deletable: bool = True


class Catalog:
    """Maps the Frame's content ids to titles, persisted per config entry."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize the catalog."""
        self._hass = hass
        self._store: Store[dict[str, dict[str, CatalogItem]]] = Store(
            hass, 1, f"{DOMAIN}.{entry_id}"
        )
        self._items: dict[str, CatalogItem] = {}

    async def async_load(self) -> None:
        """Load the saved titles."""
        data = await self._store.async_load() or {}
        self._items = dict(data.get("items") or {})

    def get(self, content_id: str) -> CatalogItem | None:
        """Return what is known about a content id."""
        return self._items.get(content_id)

    def add(self, content_id: str, title: str | None, artist: str | None) -> None:
        """Remember an upload."""
        self._items[content_id] = CatalogItem(title=title, artist=artist)
        self._save()

    def forget(self, content_id: str) -> None:
        """Forget an image deleted from the TV."""
        if self._items.pop(content_id, None) is not None:
            self._save()

    def prune(self, content_ids: set[str]) -> None:
        """Forget images that were deleted on the TV."""
        gone = self._items.keys() - content_ids
        if gone:
            for content_id in gone:
                del self._items[content_id]
            self._save()

    async def async_list(self, frame: FrameClient) -> list[FrameArt]:
        """Ask the Frame what it stores; the shown image comes first."""
        stored, current = await frame.async_list(self._hass)
        self.prune({art.content_id for art in stored})
        items = []
        for art in stored:
            known = self.get(art.content_id) or CatalogItem(title=None, artist=None)
            items.append(
                FrameArt(
                    art.content_id,
                    known["title"],
                    known["artist"],
                    art.content_id == current,
                    art.deletable,
                )
            )
        items.sort(key=lambda item: not item.current)
        return items

    async def async_remove(self) -> None:
        """Delete the stored file."""
        await self._store.async_remove()

    def _save(self) -> None:
        self._store.async_delay_save(lambda: {"items": self._items}, SAVE_DELAY)
