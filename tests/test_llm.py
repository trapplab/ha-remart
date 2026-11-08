"""Tests for the voice assistant tool."""

from unittest.mock import AsyncMock, patch

from homeassistant.components.homeassistant.exposed_entities import async_expose_entity
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm
from homeassistant.setup import async_setup_component

ENTITY_ID = "media_player.living_room_frame"


def _context() -> llm.LLMContext:
    return llm.LLMContext(
        platform="test",
        context=Context(),
        language="de",
        assistant="conversation",
        device_id=None,
    )


async def _api(hass: HomeAssistant) -> llm.APIInstance:
    return await llm.async_get_api(hass, llm.LLM_API_ASSIST, _context())


async def test_tool_only_when_exposed(hass: HomeAssistant, setup_entry) -> None:
    """The tool appears once the Frame is exposed to Assist, and calls generate."""
    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, "llm", {})
    async_expose_entity(hass, "conversation", ENTITY_ID, False)
    assert "remart__GenerateFrameArt" not in [t.name for t in (await _api(hass)).tools]

    async_expose_entity(hass, "conversation", ENTITY_ID, True)
    api = await _api(hass)
    tool = next(t for t in api.tools if t.name == "remart__GenerateFrameArt")
    assert tool.integration == "remart"

    with patch(
        "custom_components.remart.media_player.FrameArtPlayer.async_generate_and_show",
        new=AsyncMock(return_value={"revised_prompt": "a cat, oil"}),
    ) as generate:
        result = await api.async_call_tool(
            llm.ToolInput(tool_name=tool.name, tool_args={"description": "eine Katze"})
        )
    generate.assert_awaited_once_with("eine Katze")
    assert result.data == {
        "success": True,
        "frame": "Living Room Frame",
        "image_prompt": "a cat, oil",
    }

    with patch(
        "custom_components.remart.media_player.FrameArtPlayer.async_generate_and_show",
        new=AsyncMock(side_effect=HomeAssistantError("No preferred entity")),
    ):
        result = await api.async_call_tool(
            llm.ToolInput(tool_name=tool.name, tool_args={"description": "x"})
        )
    assert result.error
    assert result.data["error"] == "No preferred entity"
