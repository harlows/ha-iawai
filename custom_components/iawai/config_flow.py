
"""Configuration flow for the IAWAI Water integration."""

import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import (
    CONF_ACCOUNT_ID,
    CONF_METER_GROUP_ID,
    CONF_METER_ID,
    CONF_PASSWORD,
    CONF_SITE_ID,
    CONF_USERNAME,
    DOMAIN,
    NAME,
)
from .coordinator import IAWAIClient

_LOGGER = logging.getLogger(__name__)


class IAWAIConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for IAWAI Water."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial setup form."""
        errors = {}

        if user_input is not None:
            try:
                await self._async_validate_input(user_input)

            except ConfigEntryAuthFailed:
                errors["base"] = "invalid_auth"

            except UpdateFailed:
                _LOGGER.exception("Unable to connect to IAWAI")
                errors["base"] = "cannot_connect"

            except Exception:
                _LOGGER.exception("Unexpected error setting up IAWAI")
                errors["base"] = "unknown"

            else:
                unique_id = "_".join(
                    str(user_input[key])
                    for key in (
                        CONF_ACCOUNT_ID,
                        CONF_SITE_ID,
                        CONF_METER_GROUP_ID,
                        CONF_METER_ID,
                    )
                )

                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"{NAME} ({user_input[CONF_METER_ID]})",
                    data=user_input,
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): selector.TextSelector(
                    selector.TextSelectorConfig(
                        type=selector.TextSelectorType.PASSWORD
                    )
                ),
                vol.Required(CONF_ACCOUNT_ID): str,
                vol.Required(CONF_SITE_ID): str,
                vol.Required(CONF_METER_GROUP_ID): str,
                vol.Required(CONF_METER_ID): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def _async_validate_input(
        self, user_input: dict
    ) -> None:
        """Validate credentials by logging in to IAWAI."""
        session = async_get_clientsession(self.hass)
        client = IAWAIClient(session, user_input)

        await client.async_login()
