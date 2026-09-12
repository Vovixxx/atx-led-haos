"""Home Assistant device-registry payloads for ATX LED devices."""

from __future__ import annotations

from typing import Any

from .const import DOMAIN, MANUFACTURER


def light_device_registry_info(
    *, unique_id: str, name: str, hub_device_id: str | None = None
) -> dict[str, Any]:
    """Describe a fixture device linked to the hub by registry id.

    Home Assistant 2026.8+ requires `via_device_id` (the hub DeviceEntry.id).
    The old `via_device` identifier tuple is removed in 2027.8.
    """
    info: dict[str, Any] = {
        "identifiers": {(DOMAIN, unique_id)},
        "name": name,
        "manufacturer": MANUFACTURER,
    }
    if hub_device_id:
        info["via_device_id"] = hub_device_id
    return info

