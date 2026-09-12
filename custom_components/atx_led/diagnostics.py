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
    groups = []
    scenes = []
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
        groups = [
            {
                "device_id": group.device_id,
                "name": group.name,
                "channel": group.channel,
                "group_addr": group.group_addr,
                "kind": group.kind,
                "is_on": group.is_on,
                "stored_level": group.stored_level,
                "members": list(group.members),
                "member_count": len(group.members),
                "state_source": group.state_source,
                "has_color_temp": group.has_color_temp,
                "available": group.available,
            }
            for group in coordinator.data.groups.values()
        ]
        scenes = [
            {
                "scene_id": scene.scene_id,
                "name": scene.name,
                "channel": scene.channel,
                "dali_scene": scene.dali_scene,
                "group_addr": scene.group_addr,
                "member_count": len(scene.members),
            }
            for scene in coordinator.data.scenes.values()
        ]
    return {
        "hub_id": coordinator.hub_id,
        "host": entry.data.get(CONF_HOST),
        "light_count": len(lights),
        "group_count": len(groups),
        "scene_count": len(scenes),
        "lights": lights,
        "groups": groups,
        "scenes": scenes,
    }
