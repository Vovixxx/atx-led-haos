"""Diagnostics for ATX LED, with credentials omitted."""

from __future__ import annotations

from typing import Any

from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .coordinator import ATXLEDConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ATXLEDConfigEntry
) -> dict[str, Any]:
    """Return redacted diagnostics for a config entry."""
    coordinator = entry.runtime_data
    lights = []
    if coordinator.data is not None:
        lights = [
            {
                "device_id": light.device_id,
                "name": light.name,
                "channel": light.channel,
                "short_addr": light.short_addr,
                "is_on": light.is_on,
                "has_color_temp": light.has_color_temp,
                "status": light.status,
                "available": light.available,
            }
            for light in coordinator.data.lights.values()
        ]
    return {
        "hub_id": coordinator.hub_id,
        "host": entry.data.get(CONF_HOST),
        "light_count": len(lights),
        "lights": lights,
    }
