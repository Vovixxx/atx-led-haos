from __future__ import annotations

import json
from typing import Any

import pytest

from atx_led.client import ATXLEDApiError, ATXLEDAuthError, ATXLEDClient, ATXLEDConnectionError
from atx_led.models import parse_scenes, reconcile_lights


class FakeResponse:
    def __init__(self, status: int, payload: Any, text: str | None = None) -> None:
        self.status = status
        self._payload = payload
        self._text = text if text is not None else (
            json.dumps(payload) if not isinstance(payload, str) else payload
        )

    async def json(self) -> Any:
        if isinstance(self._payload, str):
            raise json.JSONDecodeError("not json", self._payload, 0)
        return self._payload

    async def text(self) -> str:
        return self._text

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


class FakeSession:
    def __init__(self, routes: dict[tuple[str, str], FakeResponse]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def _response(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((method, url, kwargs))
        key = (method, url)
        if key not in self.routes:
            raise AssertionError(f"unexpected request {key}")
        return self.routes[key]

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        return self._response("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        return self._response("POST", url, **kwargs)


def _client(session: FakeSession) -> ATXLEDClient:
    return ATXLEDClient(host="192.168.1.50", session=session)


async def test_get_devices_and_addresses(devices_payload: dict, addresses_payload: dict) -> None:
    session = FakeSession(
        {
            ("GET", "http://192.168.1.50/dali/api/addresses"): FakeResponse(200, addresses_payload),
            ("GET", "http://192.168.1.50/dali/api/devices"): FakeResponse(200, devices_payload),
        }
    )
    client = _client(session)
    lights = await client.async_discover_lights()
    assert [light.device_id for light in lights] == ["0_s_1", "0_s_11", "0_s_21", "0_s_16"]


async def test_discover_inventory_includes_groups_and_best_effort_scenes(
    devices_payload: dict, addresses_payload: dict, scenes_payload: dict
) -> None:
    session = FakeSession(
        {
            ("GET", "http://192.168.1.50/dali/api/addresses"): FakeResponse(200, addresses_payload),
            ("GET", "http://192.168.1.50/dali/api/devices"): FakeResponse(200, devices_payload),
            ("GET", "http://192.168.1.50/dali/api/groups"): FakeResponse(404, {"error": "missing"}),
            ("GET", "http://192.168.1.50/dali/api/scenes"): FakeResponse(200, scenes_payload),
        }
    )
    client = _client(session)
    lights, groups, scenes = await client.async_discover_inventory()
    assert [light.device_id for light in lights] == ["0_s_1", "0_s_11", "0_s_21", "0_s_16"]
    assert [group.device_id for group in groups] == ["0_g_1", "0_v_0"]
    assert [scene.scene_id for scene in scenes] == ["0_sc_0", "0_sc_1"]


async def test_missing_scenes_endpoint_does_not_fail_inventory(
    devices_payload: dict, addresses_payload: dict
) -> None:
    session = FakeSession(
        {
            ("GET", "http://192.168.1.50/dali/api/addresses"): FakeResponse(200, addresses_payload),
            ("GET", "http://192.168.1.50/dali/api/devices"): FakeResponse(200, devices_payload),
            ("GET", "http://192.168.1.50/dali/api/groups"): FakeResponse(404, {"error": "missing"}),
            ("GET", "http://192.168.1.50/dali/api/scenes"): FakeResponse(404, {"error": "missing"}),
        }
    )
    client = _client(session)
    lights, groups, scenes = await client.async_discover_inventory()
    assert lights
    assert groups
    assert scenes == []


async def test_401_is_auth_error() -> None:
    session = FakeSession(
        {("GET", "http://192.168.1.50/dali/api/addresses"): FakeResponse(401, {"error": "auth"})}
    )
    client = _client(session)
    with pytest.raises(ATXLEDAuthError):
        await client.async_get_addresses()


async def test_malformed_json_is_api_error() -> None:
    session = FakeSession(
        {("GET", "http://192.168.1.50/dali/api/devices"): FakeResponse(200, "nope", text="nope")}
    )
    client = _client(session)
    with pytest.raises(ATXLEDApiError):
        await client.async_get_devices()


async def test_send_raw_encodes_json_body() -> None:
    session = FakeSession(
        {
            ("POST", "http://192.168.1.50/dali/api/send-raw"): FakeResponse(
                200, {"ok": True, "responses": ["N"]}
            )
        }
    )
    client = _client(session)
    result = await client.async_set_level(channel=0, short_addr=1, level=185)
    assert result.ok is True
    assert result.responses[0].value is None
    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url.endswith("/dali/api/send-raw")
    assert kwargs["json"] == {"channel": 0, "commands": ["h02B9"]}


async def test_http_error_is_not_treated_as_off() -> None:
    session = FakeSession(
        {("POST", "http://192.168.1.50/dali/api/send-raw"): FakeResponse(500, {"ok": False})}
    )
    client = _client(session)
    with pytest.raises(ATXLEDApiError):
        await client.async_set_level(channel=0, short_addr=1, level=0)


async def test_connection_error_wraps_os_error() -> None:
    class BoomSession(FakeSession):
        def get(self, url: str, **kwargs: Any) -> FakeResponse:
            raise OSError("offline")

    client = ATXLEDClient(host="192.168.1.50", session=BoomSession({}))
    with pytest.raises(ATXLEDConnectionError):
        await client.async_get_devices()


def test_devices_websocket_url_is_verified_path() -> None:
    client = ATXLEDClient(host="192.168.1.50", session=FakeSession({}))
    assert client.websocket_devices_url == "ws://192.168.1.50/ws/dali/devices"
    assert client.websocket_groups_url == "ws://192.168.1.50/ws/dali/groups"


async def test_set_group_level_uses_group_dapc() -> None:
    session = FakeSession(
        {
            ("POST", "http://192.168.1.50/dali/api/send-raw"): FakeResponse(
                200, {"ok": True, "responses": ["N"]}
            )
        }
    )
    client = _client(session)
    result = await client.async_set_group_level(channel=0, group_addr=1, level=185)
    assert result.ok is True
    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url.endswith("/dali/api/send-raw")
    assert kwargs["json"] == {"channel": 0, "commands": ["h82B9"]}


async def test_recall_scene_sends_individual_go_to_scene(
    addresses_payload: dict, devices_payload: dict, scenes_payload: dict
) -> None:
    session = FakeSession(
        {
            ("POST", "http://192.168.1.50/dali/api/send-raw"): FakeResponse(
                200, {"ok": True, "responses": ["N", "N"]}
            )
        }
    )
    client = _client(session)
    lights = {
        light.device_id: light
        for light in reconcile_lights(addresses_payload, devices_payload)
    }
    scene = parse_scenes(scenes_payload)[0]
    await client.async_recall_scene(scene, lights)
    _method, _url, kwargs = session.calls[0]
    assert kwargs["json"] == {"channel": 0, "commands": ["h0310", "h1710"]}


async def test_recall_scene_prefers_group_go_to_scene(scenes_payload: dict) -> None:
    session = FakeSession(
        {
            ("POST", "http://192.168.1.50/dali/api/send-raw"): FakeResponse(
                200, {"ok": True, "responses": ["N"]}
            )
        }
    )
    client = _client(session)
    scene = parse_scenes(scenes_payload)[1]
    await client.async_recall_scene(scene, {})
    _method, _url, kwargs = session.calls[0]
    assert kwargs["json"] == {"channel": 0, "commands": ["h8311"]}


async def test_set_device_level_posts_hub_level() -> None:
    session = FakeSession(
        {
            ("POST", "http://192.168.1.50/dali/api/devices/0_s_51"): FakeResponse(
                200, {"ok": True}
            )
        }
    )
    client = _client(session)
    await client.async_set_device_level("0_s_51", 180)
    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url.endswith("/dali/api/devices/0_s_51")
    assert kwargs["json"] == {"level": 180}
