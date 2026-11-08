"""LLM tool that lets the voice assistant paint a picture onto the Frame."""

from typing import override

import probatio

from homeassistant.components.homeassistant import async_should_expose
from homeassistant.components.llm import LLMTools
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.llm import (
    LLM_API_ASSIST,
    LLMContext,
    Tool,
    ToolAnnotations,
    ToolInput,
    ToolResult,
)

from .const import ATTR_DESCRIPTION, DOMAIN
from .media_player import FrameArtPlayer
from .models import RemArtConfigEntry


class GenerateFrameArtTool(Tool):
    """Generate an image from a description and show it on the Frame."""

    name = f"{DOMAIN}__GenerateFrameArt"
    title = "Generate art for the Frame TV"
    description = (
        "Generates a new image with AI from the user's description and shows it "
        "on the Samsung Frame TV in art mode. Use when the user asks to paint, "
        "draw, create or show a picture on the Frame or TV. Pass the user's "
        "description in their own words, adding style details they mention. "
        "Takes up to a minute."
    )
    annotations = ToolAnnotations(destructive=False)
    integration = DOMAIN

    def __init__(self, players: dict[str, FrameArtPlayer]) -> None:
        """Initialize the tool for the exposed Frames."""
        self._players = players
        schema = {
            probatio.Required(
                ATTR_DESCRIPTION, description="What the picture should show"
            ): str,
        }
        if len(players) > 1:
            schema[probatio.Optional("frame", description="Which Frame TV")] = (
                probatio.In(list(players))
            )
        self.parameters = probatio.Schema(schema)

    @override
    async def async_call(
        self, hass: HomeAssistant, tool_input: ToolInput, llm_context: LLMContext
    ) -> ToolResult:
        """Generate and show the image."""
        args = self.parameters(tool_input.tool_args)
        name = args.get("frame") or next(iter(self._players))
        player = self._players[name]
        try:
            result = await player.async_generate_and_show(args[ATTR_DESCRIPTION])
        except HomeAssistantError as err:
            return ToolResult(data={"success": False, "error": str(err)}, error=True)
        return ToolResult(
            data={
                "success": True,
                "frame": name,
                "image_prompt": result.get("revised_prompt") if result else None,
            }
        )


@callback
def async_get_tools(
    hass: HomeAssistant, llm_context: LLMContext, api_id: str
) -> LLMTools | None:
    """Offer the tool when at least one Frame is exposed to the assistant."""
    if api_id != LLM_API_ASSIST:
        return None
    entries: list[RemArtConfigEntry] = hass.config_entries.async_loaded_entries(DOMAIN)
    players = {
        entry.title: player
        for entry in entries
        if (player := entry.runtime_data.player) is not None
        and player.entity_id
        and async_should_expose(hass, llm_context.assistant, player.entity_id)
    }
    if not players:
        return None
    return LLMTools(tools=[GenerateFrameArtTool(players)])
