"""Shared fixtures."""

import io
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from PIL import Image
import pytest

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.remart.const import CONF_SOURCES, CONF_TOKEN, DOMAIN
from custom_components.remart.frame import DeviceInfo
from custom_components.remart.sources import Artwork

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom_components in every test."""


def load_fixture(name: str):
    """Load a JSON fixture."""
    return json.loads((FIXTURES / name).read_text())


def png_bytes(width: int, height: int, color=(200, 30, 30)) -> bytes:
    """Return a solid PNG."""
    out = io.BytesIO()
    Image.new("RGB", (width, height), color).save(out, "PNG")
    return out.getvalue()


ARTWORK = Artwork(
    id="28560",
    source_id="chicago",
    image_url="https://example.org/bedroom.jpg",
    thumb_url="https://example.org/bedroom_thumb.jpg",
    title="The Bedroom",
    artist="Vincent van Gogh",
)


@pytest.fixture
def config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """A paired Frame."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Living Room Frame",
        unique_id="uuid:frame-1",
        data={
            CONF_HOST: "192.0.2.10",
            CONF_PORT: 8002,
            CONF_TOKEN: "tok",
            "model": "QE55LS03",
        },
        options={CONF_SOURCES: ["chicago"]},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def mock_show():
    """Patch the upload to the TV; returns the mock."""
    with patch(
        "custom_components.remart.frame.FrameClient.async_show",
        new=AsyncMock(return_value="MY_F0001"),
    ) as mock:
        yield mock


@pytest.fixture
def mock_page():
    """Patch the Chicago source to return one artwork."""
    with patch(
        "custom_components.remart.sources.museums.ChicagoSource.fetch_page",
        new=AsyncMock(return_value=[ARTWORK]),
    ) as mock:
        yield mock


@pytest.fixture
def mock_pair():
    """Patch pairing."""
    with patch(
        "custom_components.remart.frame.FrameClient.pair",
        return_value=DeviceInfo(
            unique_id="uuid:frame-1", model="QE55LS03", name="Living Room Frame"
        ),
    ) as mock:
        yield mock


@pytest.fixture
async def setup_entry(
    hass: HomeAssistant, aioclient_mock, config_entry, mock_show, mock_page
):
    """Set up the integration with media_source loaded."""
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, "media_source", {})
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry
