"""Config flow for ATX LED."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig, SelectSelectorMode

from .client import ATXLEDApiError, ATXLEDAuthError, ATXLEDClient, ATXLEDConnectionError
from .const import (
    CONF_DEVICE_ID,
    CONF_UNSIGNED_OVERRIDES,
    DOMAIN,
    MODE_CCT,
    MODE_DIMMER,
    MODE_RGB,
    MODE_RGB_CCT,
)
from .models import hub_unique_id, normalize_host
from .unsigned import (
    UnsignedOverrideError,
    merge_unsigned_override,
    normalize_unsigned_override,
    suggested_tune_values,
    unsigned_device_choices,
)

_MODE_OPTIONS = [
    {"value": MODE_DIMMER, "label": "Dimmer"},
    {"value": MODE_CCT, "label": "CCT"},
    {"value": MODE_RGB, "label": "RGB"},
    {"value": MODE_RGB_CCT, "label": "RGB+CCT"},
]

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

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return ATXLEDOptionsFlow()

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


class ATXLEDOptionsFlow(OptionsFlow):
    """Tune unsigned leftover drivers without writing hub configuration."""

    def __init__(self) -> None:
        self._device_id: str | None = None

    def _unsigned_lights(self) -> dict:
        coordinator = getattr(self.config_entry, "runtime_data", None)
        if coordinator is None or coordinator.data is None:
            return {}
        return {
            device_id: light
            for device_id, light in coordinator.data.lights.items()
            if light.unsigned
        }

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        lights = self._unsigned_lights()
        choices = unsigned_device_choices(lights)
        if not choices:
            return self.async_abort(reason="no_unsigned")
        if user_input is not None:
            self._device_id = str(user_input[CONF_DEVICE_ID])
            return await self.async_step_tune()
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE_ID): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"value": device_id, "label": label}
                                for device_id, label in choices.items()
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def async_step_tune(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        lights = self._unsigned_lights()
        device_id = self._device_id
        if device_id is None or device_id not in lights:
            return await self.async_step_init()
        light = lights[device_id]
        stored = (self.config_entry.options.get(CONF_UNSIGNED_OVERRIDES) or {}).get(device_id)
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                override = normalize_unsigned_override(user_input)
            except UnsignedOverrideError as err:
                errors["base"] = err.code
            else:
                options = merge_unsigned_override(
                    dict(self.config_entry.options), device_id, override
                )
                return self.async_create_entry(title="", data=options)
        suggested = suggested_tune_values(light, stored if isinstance(stored, dict) else None)
        return self.async_show_form(
            step_id="tune",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required("mode"): SelectSelector(
                            SelectSelectorConfig(
                                options=_MODE_OPTIONS,
                                mode=SelectSelectorMode.DROPDOWN,
                            )
                        ),
                        vol.Required("min_level"): int,
                        vol.Required("max_level"): int,
                        vol.Optional("kelvin_min"): int,
                        vol.Optional("kelvin_max"): int,
                    }
                ),
                suggested,
            ),
            errors=errors,
            description_placeholders={"name": light.name, "device_id": device_id},
        )
