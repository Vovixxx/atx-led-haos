"""Config flow for ATX LED."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import ATXLEDApiError, ATXLEDAuthError, ATXLEDClient, ATXLEDConnectionError
from .const import DOMAIN
from .models import hub_unique_id, normalize_host

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_USERNAME): str,
        vol.Optional(CONF_PASSWORD): str,
    }
)


async def _validate_hub(
    hass: HomeAssistant,
    host: str,
    username: str | None,
    password: str | None,
) -> tuple[str, int]:
    client = ATXLEDClient(
        host=host,
        session=async_get_clientsession(hass),
        username=username,
        password=password,
    )
    lights = await client.async_discover_lights()
    return client.host, len(lights)


class ATXLEDConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle an ATX LED config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect the hub address and discover commissioned lights."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = normalize_host(user_input[CONF_HOST])
            username = user_input.get(CONF_USERNAME) or None
            password = user_input.get(CONF_PASSWORD) or None
            try:
                normalized_host, light_count = await _validate_hub(
                    self.hass, host, username, password
                )
            except ATXLEDAuthError:
                errors["base"] = "invalid_auth"
            except ATXLEDConnectionError:
                errors["base"] = "cannot_connect"
            except ATXLEDApiError:
                errors["base"] = "invalid_response"
            else:
                await self.async_set_unique_id(hub_unique_id(normalized_host))
                self._abort_if_unique_id_configured(updates={CONF_HOST: normalized_host})
                data: dict[str, Any] = {CONF_HOST: normalized_host}
                if username:
                    data[CONF_USERNAME] = username
                    data[CONF_PASSWORD] = password or ""
                return self.async_create_entry(
                    title=f"ATX LED Hub ({light_count} lights)",
                    data=data,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Update the hub host without changing entity unique IDs."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            host = normalize_host(user_input[CONF_HOST])
            username = user_input.get(CONF_USERNAME) or None
            password = user_input.get(CONF_PASSWORD) or None
            try:
                normalized_host, _light_count = await _validate_hub(
                    self.hass, host, username, password
                )
            except ATXLEDAuthError:
                errors["base"] = "invalid_auth"
            except ATXLEDConnectionError:
                errors["base"] = "cannot_connect"
            except ATXLEDApiError:
                errors["base"] = "invalid_response"
            else:
                data_updates: dict[str, Any] = {CONF_HOST: normalized_host}
                if username:
                    data_updates[CONF_USERNAME] = username
                    data_updates[CONF_PASSWORD] = password or ""
                return self.async_update_reload_and_abort(
                    entry, data_updates=data_updates
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, entry.data
            ),
            errors=errors,
        )
