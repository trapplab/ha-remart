"""Tests for the config and options flow."""

from unittest.mock import patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.remart.const import (
    CONF_MATTE,
    CONF_PROMPT_PREFIX,
    CONF_SOURCES,
    CONF_TOKEN,
    DOMAIN,
)
from custom_components.remart.frame import (
    DeviceInfo,
    FrameClient,
    FrameError,
    NotAFrameError,
)


async def test_user_flow_pairs(hass: HomeAssistant) -> None:
    """A successful pairing stores host, port, token and default sources."""

    def pair(self: FrameClient) -> DeviceInfo:
        self.token = "new-token"
        return DeviceInfo(
            unique_id="uuid:frame-1", model="QE55LS03", name="Living Room Frame"
        )

    with (
        patch.object(FrameClient, "pair", autospec=True, side_effect=pair),
        patch("custom_components.remart.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.0.2.10", CONF_PORT: 8002}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Living Room Frame"
    assert result["data"] == {
        CONF_HOST: "192.0.2.10",
        CONF_PORT: 8002,
        CONF_TOKEN: "new-token",
        "model": "QE55LS03",
    }
    assert "chicago" in result["options"][CONF_SOURCES]
    assert "rijks" not in result["options"][CONF_SOURCES]
    assert result["result"].unique_id == "uuid:frame-1"


async def test_user_flow_errors(hass: HomeAssistant, mock_pair) -> None:
    """Errors are shown and the user can retry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    for exc, error in (
        (NotAFrameError("x"), "not_frame"),
        (FrameError("x"), "cannot_connect"),
    ):
        mock_pair.side_effect = exc
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.0.2.10", CONF_PORT: 8002}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": error}


async def test_already_configured(hass: HomeAssistant, config_entry, mock_pair) -> None:
    """The same TV cannot be added twice; a new host is taken over."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.0.2.99", CONF_PORT: 8002}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert config_entry.data[CONF_HOST] == "192.0.2.99"


async def test_options_flow(hass: HomeAssistant, setup_entry) -> None:
    """Options are saved and the entry reloads."""
    result = await hass.config_entries.options.async_init(setup_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_SOURCES: ["chicago", "rijks", "unsplash", "pixabay"],
            "rijks_api_key": "secret",
            "unsplash_api_key": "access",
            "photo_query": "ocean",
            CONF_MATTE: "none",
            CONF_PROMPT_PREFIX: "Oil painting: ",
        },
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert setup_entry.options["rijks_api_key"] == "secret"
    # Pixabay has no key yet, so it is skipped.
    sources = setup_entry.runtime_data.gallery.sources
    assert set(sources) == {"chicago", "rijks", "unsplash"}
    assert sources["unsplash"]._query == "ocean"


async def test_reconfigure_updates_host(
    hass: HomeAssistant, config_entry, mock_pair
) -> None:
    """A new address is stored and the entry reloads."""
    with patch("custom_components.remart.async_setup_entry", return_value=True):
        result = await config_entry.start_reconfigure_flow(hass)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "reconfigure"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.0.2.50", CONF_PORT: 8002}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_HOST] == "192.0.2.50"


async def test_reconfigure_errors_and_wrong_device(
    hass: HomeAssistant, config_entry, mock_pair
) -> None:
    """Unreachable TVs show an error; a different TV is refused."""
    result = await config_entry.start_reconfigure_flow(hass)
    mock_pair.side_effect = FrameError("timed out")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.0.2.50", CONF_PORT: 8002}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    mock_pair.side_effect = None
    mock_pair.return_value = DeviceInfo(unique_id="uuid:other", model=None, name=None)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.0.2.60", CONF_PORT: 8002}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_device"
    assert config_entry.data[CONF_HOST] != "192.0.2.60"
