"""Constants for the RemArt Frame integration."""

from typing import Final

DOMAIN: Final = "remart"

CONF_TOKEN: Final = "token"
CONF_SOURCES: Final = "sources"
CONF_MATTE: Final = "matte"
CONF_PROMPT_PREFIX: Final = "prompt_prefix"

DEFAULT_PORT: Final = 8002
DEFAULT_MATTE: Final = "none"
DEFAULT_PROMPT_PREFIX: Final = (
    "A fine-art painting in 16:9 landscape format for a framed art TV. "
    "No text, no lettering, no borders, no frame. Subject: "
)

# Name shown in the TV's "allow device" prompt.
CLIENT_NAME: Final = "HomeAssistant RemArt"

# "My Photos" category on the Frame, where uploaded images live.
MY_PICTURES_CATEGORY: Final = "MY-C0002"

PAGE_SIZE: Final = 20
PAGE_CACHE_TTL: Final = 3600

# Frame panels are 16:9; larger images are scaled down to 4K.
MAX_WIDTH: Final = 3840

# Seconds to wait for the image model before giving up.
GENERATE_TIMEOUT: Final = 180

ATTR_DESCRIPTION: Final = "description"
ATTR_AI_TASK_ENTITY: Final = "ai_task_entity"

SERVICE_GENERATE_AND_SHOW: Final = "generate_and_show"
