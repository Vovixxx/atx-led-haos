"""Async HTTP client for a local ATX LED hub."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from .models import LightDevice, normalize_host, reconcile_lights
from .protocol import dapc_frame, decode_send_raw_payload, query_status_level_max_min, SendRawResult

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

    async def async_discover_lights(self) -> list[LightDevice]:
        addresses = await self.async_get_addresses()
        devices = await self.async_get_devices()
        return reconcile_lights(addresses, devices)

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

    async def async_query_light(self, channel: int, short_addr: int) -> SendRawResult:
        return await self.async_send_raw(channel, query_status_level_max_min(short_addr))

    async def async_set_color_temp_k(self, device_id: str, kelvin: int) -> Any:
        """Set color temperature using the hub device endpoint (source-observed)."""
        async with self._lock:
            return await self._request(
                "post",
                f"/dali/api/devices/{device_id}",
                json={"color_temp_k": int(kelvin)},
            )
