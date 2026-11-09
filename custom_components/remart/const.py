"""Constants for the RemArt Frame integration."""

from typing import Final

DOMAIN: Final = "remart"

CONF_TOKEN: Final = "token"
CONF_SOURCES: Final = "sources"
CONF_MATTE: Final = "matte"
CONF_PHOTO_QUERY: Final = "photo_query"
CONF_FIT: Final = "fit"

DEFAULT_PORT: Final = 8002
DEFAULT_MATTE: Final = "none"
DEFAULT_PHOTO_QUERY: Final = "landscape"

# How images that are not 16:9 are brought to the panel's shape.
FIT_LETTERBOX: Final = "letterbox"
FIT_CROP: Final = "crop"
DEFAULT_FIT: Final = FIT_LETTERBOX

# Name shown in the TV's "allow device" prompt.
CLIENT_NAME: Final = "HomeAssistant RemArt"

# "My Photos" category on the Frame, where uploaded images live.
MY_PICTURES_CATEGORY: Final = "MY-C0002"
# Favourites repeat images that also live in another category.
FAVORITES_CATEGORY: Final = "MY-C0004"

PAGE_SIZE: Final = 20
PAGE_CACHE_TTL: Final = 3600

# Frame panels are 16:9; larger images are scaled down to 4K.
MAX_WIDTH: Final = 3840
