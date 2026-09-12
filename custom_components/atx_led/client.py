"""Async HTTP client for a local ATX LED hub."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from .models import (
    GroupDevice,
    LightDevice,
    SceneDevice,
    merge_group_records,
    normalize_host,
    parse_scenes,
    reconcile_groups,
    reconcile_lights,
    scene_short_addrs,
)
from .protocol import (
    DALI_MAX_ARC_LEVEL,
    dapc_frame,
    decode_send_raw_payload,
    go_to_scene_frame,
    group_dapc_frame,
    group_go_to_scene_frame,
    SendRawResult,
)

DEFAULT_TIMEOUT = 10.0


class ATXLEDError(Exception):
    """Base error for ATX LED client failures."""


class ATXLEDConnectionError(ATXLEDError):
    """Hub could not be reached."""


class ATXLEDAuthError(ATXLEDError):
    """Hub rejected the request as unauthorized."""


class ATXLEDApiError(ATXLEDError):
    """Hub returned an unusable response."""


class ATXLEDClient:
    """Serialized aiohttp client for inventory and raw DALI commands."""

    def __init__(
        self,
        host: str,
        session: Any,
        username: str | None = None,
        password: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.host = normalize_host(host)
        self._session = session
        self._username = username or None
        self._password = password or None
        self._timeout = timeout
        self._lock = asyncio.Lock()

    @property
    def base_url(self) -> str:
        return f"http://{self.host}"

    def _auth(self) -> Any:
        if not self._username:
            return None
        try:
            import aiohttp
        except ImportError:
            return None
        return aiohttp.BasicAuth(self._username, self._password or "")

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base_url}{path}"
        request_kwargs = dict(kwargs)
        auth = self._auth()
        if auth is not None:
            request_kwargs["auth"] = auth
        try:
            request = getattr(self._session, method.lower())
            async with request(url, **request_kwargs) as response:
                if response.status == 401:
                    raise ATXLEDAuthError("Hub authentication failed")
                if response.status >= 400:
                    body = await response.text()
                    raise ATXLEDApiError(f"HTTP {response.status}: {body[:200]}")
                try:
                    return await response.json()
                except json.JSONDecodeError as err:
                    raise ATXLEDApiError("Hub returned non-JSON") from err
                except Exception as err:
                    raise ATXLEDApiError("Hub returned an unusable body") from err
        except ATXLEDError:
            raise
        except OSError as err:
            raise ATXLEDConnectionError(str(err)) from err
        except Exception as err:
            name = type(err).__name__
            if "ClientError" in name or "Timeout" in name:
                raise ATXLEDConnectionError(str(err)) from err
            raise

    async def async_get_addresses(self) -> dict:
        payload = await self._request("get", "/dali/api/addresses")
        if not isinstance(payload, dict):
            raise ATXLEDApiError("addresses response was not an object")
        return payload

    async def async_get_devices(self) -> dict:
        payload = await self._request("get", "/dali/api/devices")
        if not isinstance(payload, dict):
            raise ATXLEDApiError("devices response was not an object")
        return payload

    async def async_get_scenes(self) -> object:
        """Read hub scenes. Missing or unusable payloads become an empty list."""
        try:
            return await self._request("get", "/dali/api/scenes")
        except ATXLEDError:
            return []

    async def async_get_groups(self) -> object:
        """Read hub group records. Missing or unusable payloads become an empty object."""
        try:
            payload = await self._request("get", "/dali/api/groups")
        except ATXLEDError:
            return {}
        return payload if isinstance(payload, dict) else {}

    async def async_discover_lights(self) -> list[LightDevice]:
        addresses = await self.async_get_addresses()
        devices = await self.async_get_devices()
        return reconcile_lights(addresses, devices)

    async def async_discover_inventory(
        self,
    ) -> tuple[list[LightDevice], list[GroupDevice], list[SceneDevice]]:
        """Read lights, groups, and scenes. Scene and groups GET failures do not fail inventory."""
        addresses = await self.async_get_addresses()
        devices = await self.async_get_devices()
        devices = merge_group_records(devices, await self.async_get_groups())
        lights = reconcile_lights(addresses, devices)
        groups = reconcile_groups(addresses, devices, lights)
        scenes_payload = await self.async_get_scenes()
        return lights, groups, parse_scenes(scenes_payload)

    async def async_send_raw(self, channel: int, commands: list[str]) -> SendRawResult:
        async with self._lock:
            payload = await self._request(
                "post",
                "/dali/api/send-raw",
                json={"channel": int(channel), "commands": commands},
            )
        if not isinstance(payload, dict):
            raise ATXLEDApiError("send-raw response was not an object")
        return decode_send_raw_payload(payload)

    async def async_set_level(self, channel: int, short_addr: int, level: int) -> SendRawResult:
        return await self.async_send_raw(channel, [dapc_frame(short_addr, level)])

    async def async_set_group_level(
        self, channel: int, group_addr: int, level: int
    ) -> SendRawResult:
        """Set a DALI group's arc level. Does not use broadcast."""
        return await self.async_send_raw(channel, [group_dapc_frame(group_addr, level)])

    @property
    def websocket_devices_url(self) -> str:
        return f"ws://{self.host}/ws/dali/devices"

    @property
    def websocket_groups_url(self) -> str:
        return f"ws://{self.host}/ws/dali/groups"

    async def _async_open_socket(self, url: str) -> Any:
        """Open a push socket. Do not send frames; listen only."""
        request_kwargs: dict[str, Any] = {"heartbeat": 30.0}
        auth = self._auth()
        if auth is not None:
            request_kwargs["auth"] = auth
        try:
            return await self._session.ws_connect(url, **request_kwargs)
        except OSError as err:
            raise ATXLEDConnectionError(str(err)) from err
        except Exception as err:
            name = type(err).__name__
            if "ClientError" in name or "Timeout" in name:
                raise ATXLEDConnectionError(str(err)) from err
            raise

    async def async_open_devices_socket(self) -> Any:
        """Open the devices push socket. Do not send frames; listen only."""
        return await self._async_open_socket(self.websocket_devices_url)

    async def async_open_groups_socket(self) -> Any:
        """Open the groups push socket. Do not send frames; listen only."""
        return await self._async_open_socket(self.websocket_groups_url)

    async def async_set_color_temp_k(self, device_id: str, kelvin: int) -> Any:
        """Set color temperature using the hub device endpoint (source-observed)."""
        async with self._lock:
            return await self._request(
                "post",
                f"/dali/api/devices/{device_id}",
                json={"color_temp_k": int(kelvin)},
            )

    async def async_set_device_level(self, device_id: str, level: int) -> Any:
        """Set brightness using the hub device endpoint so configured fade can apply."""
        raw = max(0, min(int(level), DALI_MAX_ARC_LEVEL))
        async with self._lock:
            return await self._request(
                "post",
                f"/dali/api/devices/{device_id}",
                json={"level": raw},
            )

    async def async_recall_scene(
        self,
        scene: SceneDevice,
        lights: dict[str, LightDevice] | None = None,
    ) -> SendRawResult:
        """Recall a DALI scene without broadcast.

        Prefer a listed group, then listed members, then known lights on the
        scene channel. Virtual/hub-only scenes without a DALI number fail.
        """
        if scene.dali_scene is None:
            raise ATXLEDApiError("Scene has no DALI scene number")
        channel = 0 if scene.channel is None else int(scene.channel)
        if scene.group_addr is not None:
            return await self.async_send_raw(
                channel, [group_go_to_scene_frame(scene.group_addr, scene.dali_scene)]
            )
        lights = lights or {}
        short_addrs = scene_short_addrs(scene.members, lights)
        if not short_addrs:
            short_addrs = [
                light.short_addr
                for light in lights.values()
                if scene.channel is None or light.channel == scene.channel
            ]
        if not short_addrs:
            raise ATXLEDApiError("Scene has no member fixtures to recall")
        commands = [go_to_scene_frame(addr, scene.dali_scene) for addr in short_addrs]
        return await self.async_send_raw(channel, commands)

    async def async_set_group_color_temp(
        self,
        group: GroupDevice,
        lights: dict[str, LightDevice],
        kelvin: int,
    ) -> None:
        """Set group Kelvin using verified fixture writes.

        Group device POSTs are not assumed to exist on every hub. Write each
        color-temp member. If the group has no such members, try the group id.
        """
        targets = [
            member_id
            for member_id in group.members
            if member_id in lights and lights[member_id].has_color_temp
        ]
        if not targets:
            await self.async_set_color_temp_k(group.device_id, kelvin)
            return
        for device_id in targets:
            await self.async_set_color_temp_k(device_id, kelvin)
