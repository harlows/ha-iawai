
"""Configuration flow for the IAWAI Water integration."""

import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    IAWAIAuthenticationError,
    IAWAIClient,
    IAWAIDiscoveryError,
    IAWAIError,
)
from .const import (
    CONF_OWNER_ID,
    CONF_PROJECT_ID,
    CONF_SITE_GROUP_ID,
    CONF_SITE_ID,
    CONF_PASSWORD,
    CONF_USERNAME,
    DOMAIN,
    NAME,
)

_LOGGER = logging.getLogger(__name__)


class IAWAIConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for IAWAI Water."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial setup form."""
        errors = {}

        if user_input is not None:
            try:
                session = async_get_clientsession(self.hass)
                client = IAWAIClient(
                    session=session,
                    username=user_input[CONF_USERNAME],
                    password=user_input[CONF_PASSWORD],
                )
                await client.authenticate()
                discovered = await self._async_discover(client)

            except IAWAIAuthenticationError:
                errors["base"] = "invalid_auth"

            except IAWAIDiscoveryError as err:
                _LOGGER.error("IAWAI discovery failed: %s", err)
                errors["base"] = str(err)

            except IAWAIError:
                _LOGGER.exception("Unable to connect to IAWAI")
                errors["base"] = "cannot_connect"

            except Exception:
                _LOGGER.exception("Unexpected error setting up IAWAI")
                errors["base"] = "unknown"

            else:
                data = {**user_input, **discovered}

                unique_id = "_".join(
                    str(data[key])
                    for key in (
                        CONF_OWNER_ID,
                        CONF_PROJECT_ID,
                        CONF_SITE_GROUP_ID,
                        CONF_SITE_ID,
                    )
                )

                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"{NAME} ({data[CONF_SITE_ID]})",
                    data=data,
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): selector.TextSelector(
                    selector.TextSelectorConfig(
                        type=selector.TextSelectorType.PASSWORD
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def _async_discover(self, client: IAWAIClient) -> dict:
        """Discover owner, project, site group and site IDs automatically.

        Raises IAWAIDiscoveryError for multi-owner or multi-site accounts,
        which require manual configuration (not yet supported).
        """
        owners = await client.get_accessible_owners()

        if len(owners) != 1:
            raise IAWAIDiscoveryError("multiple_owners")

        paths = await client.get_nav_paths(owners[0]["id"])

        if len(paths) != 1:
            raise IAWAIDiscoveryError("multiple_sites")

        path = paths[0]

        # Mapping confirmed against WATER_DATA_PATH ordering:
        # /api/WaterData/{owner_id}/{project_id}/{site_group_id}/{site_id}
        return {
            CONF_OWNER_ID:      path["ownerId"],
            CONF_PROJECT_ID:    path["projectId"],
            CONF_SITE_GROUP_ID: path["siteGroupId"],
            CONF_SITE_ID:       path["siteId"],
        }
