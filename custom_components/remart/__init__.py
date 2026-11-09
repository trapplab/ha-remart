"""RemArt Frame: show museum art and photos on a Samsung Frame TV."""

from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import async_setup_api
from .catalog import Catalog
from .const import (
    CONF_MATTE,
    CONF_PHOTO_QUERY,
    CONF_SOURCES,
    CONF_TOKEN,
    DEFAULT_MATTE,
    DEFAULT_PHOTO_QUERY,
    DOMAIN,
)
from .frame import FrameClient
from .gallery import Gallery
from .models import RemArtConfigEntry, RemArtData
from .sources import KEYLESS_SOURCES, SOURCES

PLATFORMS = [Platform.MEDIA_PLAYER]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


def api_key_option(source_id: str) -> str:
    """Return the options key holding a source's API key."""
    return f"{source_id}_api_key"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the HTTP and websocket API."""
    await async_setup_api(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: RemArtConfigEntry) -> bool:
    """Set up a Frame from a config entry."""
    options = entry.options
    frame = FrameClient(
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        entry.data.get(CONF_TOKEN),
        options.get(CONF_MATTE, DEFAULT_MATTE),
    )
    gallery = Gallery(
        async_get_clientsession(hass),
        options.get(CONF_SOURCES, KEYLESS_SOURCES),
        {sid: options.get(api_key_option(sid), "") for sid in SOURCES},
        options.get(CONF_PHOTO_QUERY) or DEFAULT_PHOTO_QUERY,
    )
    catalog = Catalog(hass, entry.entry_id)
    await catalog.async_load()
    entry.runtime_data = RemArtData(frame=frame, gallery=gallery, catalog=catalog)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: RemArtConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: RemArtConfigEntry) -> None:
    """Delete the titles remembered for a removed Frame."""
    await Catalog(hass, entry.entry_id).async_remove()
