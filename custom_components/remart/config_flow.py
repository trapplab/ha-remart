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
    CONF_FIT,
    CONF_MATTE,
    CONF_PHOTO_QUERY,
    CONF_PROMPT_PREFIX,
    CONF_SOURCES,
    CONF_TOKEN,
    DEFAULT_FIT,
    DEFAULT_MATTE,
    DEFAULT_PHOTO_QUERY,
    DEFAULT_PORT,
    DEFAULT_PROMPT_PREFIX,
    DOMAIN,
    FIT_CROP,
    FIT_LETTERBOX,
)
from .frame import DeviceInfo, FrameClient, FrameError, NotAFrameError
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

    async def _async_pair(
        self, user_input: dict[str, Any], token: str | None, errors: dict[str, str]
    ) -> tuple[FrameClient, DeviceInfo] | None:
        """Pair with the TV at the given address; fill ``errors`` on failure."""
        client = FrameClient(
            user_input[CONF_HOST], user_input[CONF_PORT], token, DEFAULT_MATTE
        )
        try:
            info = await self.hass.async_add_executor_job(client.pair)
        except NotAFrameError:
            errors["base"] = "not_frame"
        except FrameError as err:
            _LOGGER.debug("Pairing failed: %s", err)
            errors["base"] = "cannot_connect"
        else:
            return client, info
        return None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the TV address and pair."""
        errors: dict[str, str] = {}
        if user_input is not None and (
            paired := await self._async_pair(user_input, None, errors)
        ):
            client, info = paired
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

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the address of an already paired TV, e.g. after a new DHCP lease."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None and (
            paired := await self._async_pair(
                user_input, entry.data.get(CONF_TOKEN), errors
            )
        ):
            client, info = paired
            # Entries whose TV reported no ID fell back to the host as unique_id;
            # that cannot match at a new address, so skip the device check there.
            if entry.unique_id != entry.data[CONF_HOST]:
                await self.async_set_unique_id(info.unique_id)
                self._abort_if_unique_id_mismatch(reason="wrong_device")
            return self.async_update_reload_and_abort(
                entry,
                data_updates={
                    **user_input,
                    CONF_TOKEN: client.token,
                    "model": info.model,
                },
            )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                USER_SCHEMA, user_input or entry.data
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: RemArtConfigEntry) -> RemArtOptionsFlow:
        """Return the options flow."""
        return RemArtOptionsFlow()


class RemArtOptionsFlow(OptionsFlowWithReload):
    """Choose sources, API keys, image fit, matte and prompt."""

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
        schema[probatio.Required(CONF_FIT)] = SelectSelector(
            SelectSelectorConfig(
                options=[FIT_LETTERBOX, FIT_CROP],
                translation_key=CONF_FIT,
            )
        )
        schema[probatio.Required(CONF_MATTE)] = str
        schema[probatio.Required(CONF_PROMPT_PREFIX)] = TextSelector(
            TextSelectorConfig(multiline=True)
        )

        current = {
            CONF_SOURCES: KEYLESS_SOURCES,
            CONF_FIT: DEFAULT_FIT,
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
