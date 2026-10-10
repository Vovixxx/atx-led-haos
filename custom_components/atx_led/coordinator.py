"""Data update coordinator for ATX LED."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
import logging
import time

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import ATXLEDApiError, ATXLEDClient, ATXLEDError
from .commands import CommandPlan, group_members, plan_group, plan_light
from .const import CONF_UNSIGNED_OVERRIDES, DEFAULT_SCAN_INTERVAL, DOMAIN
from .models import (
    GroupDevice,
    LightDevice,
    SceneDevice,
    apply_derived_group_states,
    apply_device_patches,
    apply_group_patches,
    hub_unique_id,
    parse_ws_patches,
    preserve_group_live_state,
)
from .protocol import mirek_to_kelvin
from .unsigned import apply_unsigned_overrides

_LOGGER = logging.getLogger(__name__)

WS_RETRY_INITIAL = 5
WS_RETRY_MAX = 60


@dataclass(frozen=True)
class ATXLEDData:
    """Latest discovered light, group, and scene inventory."""

    lights: dict[str, LightDevice]
    groups: dict[str, GroupDevice]
    scenes: dict[str, SceneDevice]


class _TargetQueue:
    """Commands for one light or group: one running, at most one waiting."""

    def __init__(self) -> None:
        self.running = False
        self.waiting: tuple[Callable[[], Awaitable[None]], asyncio.Future[None]] | None = None


type ATXLEDConfigEntry = ConfigEntry[ATXLEDCoordinator]


class ATXLEDCoordinator(DataUpdateCoordinator[ATXLEDData]):
    """Poll hub inventory and merge live device/group WebSocket patches."""

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
        self._ws_devices = None
        self._ws_groups = None
        self._watch_started = False
        self._init_write_state()

    def _init_write_state(self) -> None:
        # Colour belongs to Home Assistant: what we last wrote (or read from the driver
        # once at start-up). The hub's color_temp_k never feeds the entities.
        self._colors: dict[str, int] = {}
        self._write_times: dict[str, float] = {}
        self._intent: dict[str, bool] = {}
        self._queues: dict[str, _TargetQueue] = {}
        self._drain_tasks: set[asyncio.Task[None]] = set()
        self._driver_colors: set[str] = set()

    @property
    def colors(self) -> dict[str, int]:
        return dict(self._colors)

    def get_light(self, device_id: str) -> LightDevice | None:
        if self.data is None:
            return None
        return self.data.lights.get(device_id)

    def get_group(self, device_id: str) -> GroupDevice | None:
        if self.data is None:
            return None
        return self.data.groups.get(device_id)

    def get_scene(self, scene_id: str) -> SceneDevice | None:
        if self.data is None:
            return None
        return self.data.scenes.get(scene_id)

    def intended_on(self, target_id: str) -> bool | None:
        """On/off the newest accepted press is heading for, while a write is pending."""
        return self._intent.get(target_id)

    def _apply_colors(
        self, lights: dict[str, LightDevice], groups: dict[str, GroupDevice]
    ) -> tuple[dict[str, LightDevice], dict[str, GroupDevice]]:
        """Overlay the written-colour map on fixtures and derive group colour from members."""
        new_lights = lights
        for device_id, light in lights.items():
            if not light.has_color_temp:
                continue
            kelvin = self._colors.get(device_id)
            if light.color_temp_k != kelvin:
                if new_lights is lights:
                    new_lights = dict(lights)
                new_lights[device_id] = replace(light, color_temp_k=kelvin)
        new_groups = groups
        for device_id, group in groups.items():
            colour_members = [
                member for member in group_members(group, new_lights) if member.has_color_temp
            ]
            if not colour_members:
                continue
            values = {member.color_temp_k for member in colour_members}
            kelvin = values.pop() if len(values) == 1 else None
            source = "derived" if kelvin is not None else "unknown"
            if group.color_temp_k != kelvin or group.color_temp_source != source:
                if new_groups is groups:
                    new_groups = dict(groups)
                new_groups[device_id] = replace(
                    group, color_temp_k=kelvin, color_temp_source=source
                )
        return new_lights, new_groups

    def async_restore_color(self, device_id: str, kelvin: int) -> None:
        """Take a restored colour for a fixture we have not written or read yet."""
        if not kelvin or (device_id in self._colors and device_id not in self._driver_colors):
            return
        # A saved Home Assistant colour beats a start-up driver read; a write of this run wins both.
        self._driver_colors.discard(device_id)
        self._colors[device_id] = int(kelvin)
        self._republish_colors()

    def _republish_colors(self) -> None:
        if self.data is None:
            return
        lights, groups = self._apply_colors(self.data.lights, self.data.groups)
        if lights is self.data.lights and groups is self.data.groups:
            return
        self._publish_ws_data(ATXLEDData(lights=lights, groups=groups, scenes=self.data.scenes))

    async def async_read_missing_colors(self) -> None:
        """Read colour once from the driver for colour fixtures never written, one at a time."""
        if self.data is None:
            return
        for light in list(self.data.lights.values()):
            if not light.has_color_temp or light.device_id in self._colors:
                continue
            try:
                mirek = await self.client.async_query_color_mirek(
                    light.channel, light.short_addr
                )
            except ATXLEDError as err:
                _LOGGER.debug("ATX LED colour read failed for %s: %s", light.device_id, err)
                continue
            kelvin = mirek_to_kelvin(mirek) if mirek else None
            if kelvin is not None and light.device_id not in self._colors:
                self._colors[light.device_id] = kelvin
                self._driver_colors.add(light.device_id)
        self._republish_colors()

    async def async_set_light(
        self, device_id: str, level: int | None, kelvin: int | None = None
    ) -> None:
        """Turn one fixture on/off in one send-raw call. ``level`` None keeps the level."""
        await self._async_submit(
            device_id, level, lambda: self._async_run_light(device_id, level, kelvin)
        )

    async def async_set_group(
        self, group_id: str, level: int | None, kelvin: int | None = None
    ) -> None:
        """Turn a DALI or virtual group on/off in one send-raw call per channel."""
        await self._async_submit(
            group_id, level, lambda: self._async_run_group(group_id, level, kelvin)
        )

    async def _async_submit(
        self, target_id: str, level: int | None, job: Callable[[], Awaitable[None]]
    ) -> None:
        if level is not None:
            self._intent[target_id] = level > 0
        queue = self._queues.setdefault(target_id, _TargetQueue())
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        entry = (job, future)
        if queue.running:
            # A newer press replaces one still waiting; the one being sent completes.
            if queue.waiting is not None and not queue.waiting[1].done():
                queue.waiting[1].set_result(None)
            queue.waiting = entry
        else:
            queue.running = True
            task = asyncio.get_running_loop().create_task(
                self._async_drain(target_id, queue, entry)
            )
            self._drain_tasks.add(task)
            task.add_done_callback(self._drain_tasks.discard)
        try:
            # Shielded: cancelling a caller never cancels the accepted press.
            await asyncio.shield(future)
        except asyncio.CancelledError:
            if queue.waiting is entry:
                queue.waiting = None  # not started yet: drop it
            raise

    async def _async_drain(
        self,
        target_id: str,
        queue: _TargetQueue,
        entry: tuple[Callable[[], Awaitable[None]], asyncio.Future[None]],
    ) -> None:
        """Run the queue in its own task so caller cancellation cannot lose accepted presses."""
        try:
            while entry is not None:
                job, future = entry
                try:
                    await job()
                except Exception as err:
                    if not future.done():
                        future.set_exception(err)
                    else:
                        _LOGGER.debug("ATX LED write failed after caller left: %s", err)
                else:
                    if not future.done():
                        future.set_result(None)
                entry, queue.waiting = queue.waiting, None
        finally:
            if queue.waiting is not None and not queue.waiting[1].done():
                queue.waiting[1].cancel()
            queue.waiting = None
            queue.running = False
            self._intent.pop(target_id, None)

    async def _async_send(self, plan: CommandPlan) -> None:
        for channel, frames in plan.frames.items():
            await self.client.async_send_raw(channel, frames)

    async def _async_run_light(
        self, device_id: str, level: int | None, kelvin: int | None
    ) -> None:
        light = self.get_light(device_id)
        if light is None:
            raise ATXLEDApiError("Light is unavailable")
        plan = plan_light(light, level, kelvin, self._colors.get(device_id))
        await self._async_send(plan)
        self._record_write([device_id], None, level, plan.colours)

    async def _async_run_group(
        self, group_id: str, level: int | None, kelvin: int | None
    ) -> None:
        group = self.get_group(group_id)
        if group is None:
            raise ATXLEDApiError("Group is unavailable")
        lights = self.data.lights if self.data is not None else {}
        plan = plan_group(group, lights, level, kelvin, self._colors)
        await self._async_send(plan)
        member_ids = [member.device_id for member in group_members(group, lights)]
        self._record_write(member_ids, group_id, level, plan.colours)

    def _record_write(
        self,
        light_ids: list[str],
        group_id: str | None,
        level: int | None,
        colours: dict[str, int],
    ) -> None:
        """Show the accepted call at once; hub data that started earlier cannot undo it."""
        if self.data is None:
            return
        now = time.monotonic()
        self._colors.update(colours)
        self._driver_colors.difference_update(colours)

        def shown(device):
            if level is None:
                return device
            if level > 0:
                return replace(device, is_on=True, stored_level=level)
            return replace(device, is_on=False)

        lights = dict(self.data.lights)
        for device_id in light_ids:
            if device_id in lights:
                lights[device_id] = shown(lights[device_id])
                self._write_times[device_id] = now
        groups = dict(self.data.groups)
        if group_id is not None and group_id in groups:
            groups[group_id] = replace(shown(groups[group_id]), state_source="derived")
            self._write_times[group_id] = now
        lights, groups = self._apply_colors(lights, groups)
        self._publish_ws_data(ATXLEDData(lights=lights, groups=groups, scenes=self.data.scenes))

    def _keep_recent_writes(
        self, data: ATXLEDData, previous: ATXLEDData | None, poll_started: float
    ) -> ATXLEDData:
        """Level and on/off we wrote after this poll started beat what the poll read."""
        if previous is None:
            return data
        lights = dict(data.lights)
        groups = dict(data.groups)
        for device_id, written_at in self._write_times.items():
            if written_at < poll_started:
                continue
            if device_id in lights and device_id in previous.lights:
                old = previous.lights[device_id]
                lights[device_id] = replace(
                    lights[device_id], is_on=old.is_on, stored_level=old.stored_level
                )
            elif device_id in groups and device_id in previous.groups:
                old_group = previous.groups[device_id]
                groups[device_id] = replace(
                    groups[device_id],
                    is_on=old_group.is_on,
                    stored_level=old_group.stored_level,
                    state_source=old_group.state_source,
                )
        return ATXLEDData(lights=lights, groups=groups, scenes=data.scenes)

    def async_start_watch(self) -> None:
        """Listen for hub push updates. Does not send light-changing commands."""
        if self._watch_started:
            return
        self._watch_started = True
        self.config_entry.async_create_background_task(
            self.hass, self._async_listen_forever("devices"), "atx-led-devices-ws"
        )
        self.config_entry.async_create_background_task(
            self.hass, self._async_listen_forever("groups"), "atx-led-groups-ws"
        )
        self.config_entry.async_on_unload(
            self.hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STOP, self._async_close_ws
            )
        )

    async def _async_close_ws(self, *_args: object) -> None:
        await self._close_ws()

    async def _close_ws(self) -> None:
        for attr in ("_ws_devices", "_ws_groups"):
            ws = getattr(self, attr)
            setattr(self, attr, None)
            if ws is not None and not getattr(ws, "closed", True):
                await ws.close()

    async def _async_listen_forever(self, kind: str) -> None:
        delay = WS_RETRY_INITIAL
        try:
            while True:
                try:
                    await self._async_listen_once(kind)
                    delay = WS_RETRY_INITIAL
                except asyncio.CancelledError:
                    raise
                except Exception as err:  # reconnect; never replay controls
                    _LOGGER.debug("ATX LED %s websocket disconnected: %s", kind, err)
                await asyncio.sleep(delay)
                delay = min(delay * 2, WS_RETRY_MAX)
        finally:
            await self._close_ws_kind(kind)

    async def _close_ws_kind(self, kind: str) -> None:
        attr = "_ws_devices" if kind == "devices" else "_ws_groups"
        ws = getattr(self, attr)
        setattr(self, attr, None)
        if ws is not None and not getattr(ws, "closed", True):
            await ws.close()

    async def _async_listen_once(self, kind: str) -> None:
        import aiohttp

        if kind == "groups":
            ws = await self.client.async_open_groups_socket()
            attr = "_ws_groups"
        else:
            ws = await self.client.async_open_devices_socket()
            attr = "_ws_devices"
        setattr(self, attr, ws)
        try:
            async for msg in ws:
                if msg.type in (aiohttp.WSMsgType.TEXT, aiohttp.WSMsgType.BINARY):
                    self._handle_ws_message(kind, msg.data)
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.ERROR,
                    aiohttp.WSMsgType.CLOSE,
                ):
                    break
        finally:
            if getattr(self, attr) is ws:
                setattr(self, attr, None)
            if not ws.closed:
                await ws.close()

    def _handle_ws_message(self, kind: str, raw: object) -> None:
        if self.data is None:
            return
        patches = parse_ws_patches(raw)
        if not patches:
            return
        if kind == "groups":
            lights = self.data.lights
            groups = apply_group_patches(self.data.groups, patches)
            groups = apply_derived_group_states(groups, lights)
        else:
            lights = apply_device_patches(self.data.lights, patches)
            groups = apply_derived_group_states(self.data.groups, lights)
        lights, groups = self._apply_colors(lights, groups)
        if lights is self.data.lights and groups is self.data.groups:
            return
        self._publish_ws_data(
            ATXLEDData(lights=lights, groups=groups, scenes=self.data.scenes)
        )

    def _publish_ws_data(self, data: ATXLEDData) -> None:
        """Notify entities of push data without postponing inventory polling."""
        self.data = data
        self.async_update_listeners()

    async def _async_update_data(self) -> ATXLEDData:
        poll_started = time.monotonic()
        try:
            lights, groups, scenes = await self.client.async_discover_inventory()
        except ATXLEDError as err:
            raise UpdateFailed(str(err)) from err
        lights_map = {light.device_id: light for light in lights}
        lights_map = apply_unsigned_overrides(
            lights_map,
            self.config_entry.options.get(CONF_UNSIGNED_OVERRIDES),
        )
        discovered_groups = {group.device_id: group for group in groups}
        previous_groups = self.data.groups if self.data is not None else {}
        groups_map = preserve_group_live_state(previous_groups, discovered_groups)
        groups_map = apply_derived_group_states(groups_map, lights_map)
        lights_map, groups_map = self._apply_colors(lights_map, groups_map)
        data = ATXLEDData(
            lights=lights_map,
            groups=groups_map,
            scenes={scene.scene_id: scene for scene in scenes},
        )
        return self._keep_recent_writes(data, self.data, poll_started)
