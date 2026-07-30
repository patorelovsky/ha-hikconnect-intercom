"""Config flow for the Hik-Connect Intercom (Cloud) integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResult

from .const import CONF_CHANNEL, CONF_MEDIA_KEY, CONF_SERIAL, DEFAULT_CHANNEL, DOMAIN
from .relay import hik_connect_login

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_SERIAL): str,
        vol.Required(CONF_CHANNEL, default=DEFAULT_CHANNEL): int,
        vol.Required(CONF_MEDIA_KEY): str,
    }
)


class HikConnectIntercomConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hik-Connect Intercom (Cloud)."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            unique_id = f"{user_input[CONF_SERIAL]}_{user_input[CONF_CHANNEL]}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            try:
                await self.hass.async_add_executor_job(
                    hik_connect_login, user_input[CONF_EMAIL], user_input[CONF_PASSWORD]
                )
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Hik-Connect login failed during config flow")
                errors["base"] = "cannot_connect"
            else:
                title = f"Hik-Connect Intercom ({user_input[CONF_SERIAL]} ch{user_input[CONF_CHANNEL]})"
                return self.async_create_entry(title=title, data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )
