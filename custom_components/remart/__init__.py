"""RemArt Frame: show museum art and AI images on a Samsung Frame TV."""

import probatio

from homeassistant.components.media_player import DOMAIN as MEDIA_PLAYER_DOMAIN
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.helpers import config_validation as cv, service
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_AI_TASK_ENTITY,
    ATTR_DESCRIPTION,
    CONF_MATTE,
    CONF_SOURCES,
    CONF_TOKEN,
    DEFAULT_MATTE,
    DOMAIN,
    SERVICE_GENERATE_AND_SHOW,
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
    """Register the integration's services."""
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_GENERATE_AND_SHOW,
        entity_domain=MEDIA_PLAYER_DOMAIN,
        schema={
            probatio.Required(ATTR_DESCRIPTION): cv.string,
            probatio.Optional(ATTR_AI_TASK_ENTITY): cv.entity_domain("ai_task"),
        },
        func="async_generate_and_show",
        supports_response=SupportsResponse.OPTIONAL,
    )
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
    )
    entry.runtime_data = RemArtData(frame=frame, gallery=gallery)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: RemArtConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
