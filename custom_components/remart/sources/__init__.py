"""Museum art sources."""

from .base import ArtSource, Artwork
from .museums import (
    ChicagoSource,
    ClevelandSource,
    EuropeanaSource,
    MetSource,
    MiaSource,
    RijksSource,
    SmithsonianSource,
    SmkSource,
)
from .wikimedia import WikimediaSource

SOURCES: dict[str, type[ArtSource]] = {
    cls.source_id: cls
    for cls in (
        ChicagoSource,
        MetSource,
        ClevelandSource,
        SmkSource,
        MiaSource,
        WikimediaSource,
        RijksSource,
        EuropeanaSource,
        SmithsonianSource,
    )
}

KEYLESS_SOURCES = [sid for sid, cls in SOURCES.items() if not cls.requires_api_key]

__all__ = ["KEYLESS_SOURCES", "SOURCES", "ArtSource", "Artwork"]
