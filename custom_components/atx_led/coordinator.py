"""Data update coordinator for ATX LED."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import ATXLEDClient, ATXLEDError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .models import LightDevice, apply_device_patches, hub_unique_id, parse_ws_patches

_LOGGER = logging.getLogger(__name__)

WS_RETRY_INITIAL = 5
WS_RETRY_MAX = 60


@dataclass(frozen=True)
class ATXLEDData:
    """Latest discovered light inventory."""

    lights: dict[str, LightDevice]


type ATXLEDConfigEntry = ConfigEntry[ATXLEDCoordinator]


class ATXLEDCoordinator(DataUpdateCoordinator[ATXLEDData]):
    """Poll hub inventory and merge live `/ws/dali/devices` patches."""

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
        self._ws = None
        self._watch_started = False

    def get_light(self, device_id: str) -> LightDevice | None:
        if self.data is None:
            return None
        return self.data.lights.get(device_id)

    def async_start_watch(self) -> None:
        """Listen for hub push updates. Does not send light-changing commands."""
        if self._watch_started:
            return
        self._watch_started = True
        self.config_entry.async_create_background_task(
            self.hass, self._async_listen_forever(), "atx-led-devices-ws"
        )
        self.config_entry.async_on_unload(
            self.hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STOP, self._async_close_ws
            )
        )

    async def _async_close_ws(self, *_args: object) -> None:
        await self._close_ws()

    async def _close_ws(self) -> None:
        ws = self._ws
        self._ws = None
        if ws is not None and not getattr(ws, "closed", True):
            await ws.close()

    async def _async_listen_forever(self) -> None:
        delay = WS_RETRY_INITIAL
        try:
            while True:
                try:
                    await self._async_listen_once()
                    delay = WS_RETRY_INITIAL
                except asyncio.CancelledError:
                    raise
                except Exception as err:  # reconnect; never replay controls
                    _LOGGER.debug("ATX LED websocket disconnected: %s", err)
                await asyncio.sleep(delay)
                delay = min(delay * 2, WS_RETRY_MAX)
        finally:
            await self._close_ws()

    async def _async_listen_once(self) -> None:
        import aiohttp

        ws = await self.client.async_open_devices_socket()
        self._ws = ws
        try:
            async for msg in ws:
                if msg.type in (aiohttp.WSMsgType.TEXT, aiohttp.WSMsgType.BINARY):
                    self._handle_ws_message(msg.data)
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.ERROR,
                    aiohttp.WSMsgType.CLOSE,
                ):
                    break
        finally:
            if self._ws is ws:
                self._ws = None
            if not ws.closed:
                await ws.close()

    def _handle_ws_message(self, raw: object) -> None:
        if self.data is None:
            return
        patches = parse_ws_patches(raw)
        if not patches:
            return
        lights = apply_device_patches(self.data.lights, patches)
        if lights is self.data.lights:
            return
        self.async_set_updated_data(ATXLEDData(lights=lights))

    async def _async_update_data(self) -> ATXLEDData:
        try:
            lights = await self.client.async_discover_lights()
        except ATXLEDError as err:
            raise UpdateFailed(str(err)) from err
        return ATXLEDData(lights={light.device_id: light for light in lights})
