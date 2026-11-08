"""Runtime data for RemArt config entries."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry

from .catalog import Catalog
from .frame import FrameClient
from .gallery import Gallery

if TYPE_CHECKING:
    from .media_player import FrameArtPlayer


@dataclass(slots=True)
class RemArtData:
    """Objects shared by the platforms of one Frame."""

    frame: FrameClient
    gallery: Gallery
    catalog: Catalog
    player: FrameArtPlayer | None = None


type RemArtConfigEntry = ConfigEntry[RemArtData]
