"""Config flow for RemArt Frame."""

import logging
from typing import Any

import probatio

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from . import api_key_option
from .const import (
    CONF_MATTE,
    CONF_PHOTO_QUERY,
    CONF_PROMPT_PREFIX,
    CONF_SOURCES,
    CONF_TOKEN,
    DEFAULT_MATTE,
    DEFAULT_PHOTO_QUERY,
    DEFAULT_PORT,
    DEFAULT_PROMPT_PREFIX,
    DOMAIN,
)
from .frame import FrameClient, FrameError, NotAFrameError
from .models import RemArtConfigEntry
from .sources import KEYLESS_SOURCES, SOURCES

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_HOST): str,
        probatio.Required(CONF_PORT, default=DEFAULT_PORT): int,
    }
)


class RemArtConfigFlow(ConfigFlow, domain=DOMAIN):
    """Pair with a Frame TV."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the TV address and pair."""
        errors: dict[str, str] = {}
        if user_input is not None:
            client = FrameClient(
                user_input[CONF_HOST], user_input[CONF_PORT], None, DEFAULT_MATTE
            )
            try:
                info = await self.hass.async_add_executor_job(client.pair)
            except NotAFrameError:
                errors["base"] = "not_frame"
            except FrameError as err:
                _LOGGER.debug("Pairing failed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(info.unique_id)
                self._abort_if_unique_id_configured(updates=user_input)
                return self.async_create_entry(
                    title=info.name or "Frame TV",
                    data={**user_input, CONF_TOKEN: client.token, "model": info.model},
                    options={CONF_SOURCES: KEYLESS_SOURCES},
                )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: RemArtConfigEntry) -> RemArtOptionsFlow:
        """Return the options flow."""
        return RemArtOptionsFlow()


class RemArtOptionsFlow(OptionsFlowWithReload):
    """Choose sources, API keys, matte and prompt."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        schema: dict[Any, Any] = {
            probatio.Required(CONF_SOURCES): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value=sid, label=cls.name)
                        for sid, cls in SOURCES.items()
                    ],
                    multiple=True,
                )
            ),
        }
        for sid, cls in SOURCES.items():
            if cls.requires_api_key:
                schema[probatio.Optional(api_key_option(sid))] = TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                )
        schema[probatio.Optional(CONF_PHOTO_QUERY)] = str
        schema[probatio.Required(CONF_MATTE)] = str
        schema[probatio.Required(CONF_PROMPT_PREFIX)] = TextSelector(
            TextSelectorConfig(multiline=True)
        )

        current = {
            CONF_SOURCES: KEYLESS_SOURCES,
            CONF_MATTE: DEFAULT_MATTE,
            CONF_PHOTO_QUERY: DEFAULT_PHOTO_QUERY,
            CONF_PROMPT_PREFIX: DEFAULT_PROMPT_PREFIX,
            **self.config_entry.options,
        }
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                probatio.Schema(schema), current
            ),
        )
