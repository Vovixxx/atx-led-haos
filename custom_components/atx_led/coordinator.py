"""Data update coordinator for ATX LED."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import ATXLEDClient, ATXLEDError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .models import LightDevice, hub_unique_id

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ATXLEDData:
    """Latest discovered light inventory."""

    lights: dict[str, LightDevice]


type ATXLEDConfigEntry = ConfigEntry[ATXLEDCoordinator]


class ATXLEDCoordinator(DataUpdateCoordinator[ATXLEDData]):
    """Poll hub inventory without sending DALI control commands."""

    config_entry: ATXLEDConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ATXLEDConfigEntry,
        client: ATXLEDClient,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
            always_update=False,
        )
        self.client = client
        self.host = entry.data[CONF_HOST]
        self.hub_id = entry.unique_id or hub_unique_id(self.host)
        self.hub_device_id: str | None = None

    def get_light(self, device_id: str) -> LightDevice | None:
        if self.data is None:
            return None
        return self.data.lights.get(device_id)

    async def _async_update_data(self) -> ATXLEDData:
        try:
            lights = await self.client.async_discover_lights()
        except ATXLEDError as err:
            raise UpdateFailed(str(err)) from err
        return ATXLEDData(lights={light.device_id: light for light in lights})
