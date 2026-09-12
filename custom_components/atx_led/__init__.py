"""The ATX LED Home Assistant integration."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .client import ATXLEDClient
from .const import DOMAIN, HUB_MODEL, MANUFACTURER
from .coordinator import ATXLEDConfigEntry, ATXLEDCoordinator

PLATFORMS = (Platform.LIGHT,)
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the ATX LED integration."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ATXLEDConfigEntry) -> bool:
    """Set up ATX LED from a config entry. Discovery does not change lights."""
    session = async_get_clientsession(hass)
    client = ATXLEDClient(
        host=entry.data[CONF_HOST],
        session=session,
        username=entry.data.get(CONF_USERNAME),
        password=entry.data.get(CONF_PASSWORD),
    )
    coordinator = ATXLEDCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    device_registry = dr.async_get(hass)
    hub_device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, coordinator.hub_id)},
        manufacturer=MANUFACTURER,
        model=HUB_MODEL,
        name="ATX LED Hub",
        configuration_url=f"http://{coordinator.host}/dali/devices",
    )
    coordinator.hub_device_id = hub_device.id
    coordinator.async_start_watch()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ATXLEDConfigEntry) -> bool:
    """Unload an ATX LED config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
