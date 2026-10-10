"""Group turn_on must send the level before slow member Kelvin writes."""

from __future__ import annotations

import importlib
import sys
import types
from typing import Generic, TypeVar

import pytest

from atx_led.models import GroupDevice, reconcile_lights


@pytest.fixture
def light_module(monkeypatch: pytest.MonkeyPatch):
    """Load the light platform with a small stand-in for unavailable HA modules."""

    def module(name: str, package: bool = False) -> types.ModuleType:
        mod = types.ModuleType(name)
        if package:
            mod.__path__ = []
        return mod

    data_type = TypeVar("data_type")

    class CoordinatorEntity(Generic[data_type]):
        def __init__(self, coordinator) -> None:
            self.coordinator = coordinator

    class DataUpdateCoordinator(Generic[data_type]):
        pass

    homeassistant = module("homeassistant", package=True)
    components = module("homeassistant.components", package=True)
    light = module("homeassistant.components.light")
    light.ATTR_BRIGHTNESS = "brightness"
    light.ATTR_COLOR_TEMP_KELVIN = "color_temp_kelvin"
    light.ColorMode = types.SimpleNamespace(COLOR_TEMP="color_temp", BRIGHTNESS="brightness")
    light.LightEntity = type("LightEntity", (), {})
    config_entries = module("homeassistant.config_entries")
    config_entries.ConfigEntry = type(
        "ConfigEntry", (), {"__class_getitem__": classmethod(lambda cls, _: cls)}
    )
    const = module("homeassistant.const")
    const.CONF_HOST = "host"
    const.EVENT_HOMEASSISTANT_STOP = "stop"
    core = module("homeassistant.core")
    core.HomeAssistant = type("HomeAssistant", (), {})
    core.callback = lambda func: func
    exceptions = module("homeassistant.exceptions")
    exceptions.HomeAssistantError = type("HomeAssistantError", (Exception,), {})
    helpers = module("homeassistant.helpers", package=True)
    device_registry = module("homeassistant.helpers.device_registry")
    device_registry.DeviceInfo = dict
    helpers.device_registry = device_registry
    entity_platform = module("homeassistant.helpers.entity_platform")
    entity_platform.AddConfigEntryEntitiesCallback = object
    update_coordinator = module("homeassistant.helpers.update_coordinator")
    update_coordinator.CoordinatorEntity = CoordinatorEntity
    update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
    update_coordinator.UpdateFailed = type("UpdateFailed", (Exception,), {})
    modules = (
        homeassistant, components, light, config_entries, const, core, exceptions,
        helpers, device_registry, entity_platform, update_coordinator,
    )
    with monkeypatch.context() as patch:
        for mod in modules:
            patch.setitem(sys.modules, mod.__name__, mod)
        for name in ("atx_led.light", "atx_led.coordinator"):
            sys.modules.pop(name, None)
        yield importlib.import_module("atx_led.light")
        for name in ("atx_led.light", "atx_led.coordinator"):
            sys.modules.pop(name, None)


class RecordingClient:
    def __init__(self, calls: list) -> None:
        self.calls = calls

    async def async_set_group_level(self, channel, group_addr, level):
        self.calls.append(("level", level))

    async def async_set_group_color_temp(self, group, lights, kelvin):
        self.calls.append(("kelvin", kelvin))


class FakeCoordinator:
    def __init__(self, group: GroupDevice, lights: dict) -> None:
        self.calls: list = []
        self.client = RecordingClient(self.calls)
        self.data = types.SimpleNamespace(lights=lights, groups={group.device_id: group})
        self._group = group

    def get_group(self, device_id):
        return self._group

    def async_group_color_temp_written(self, device_id, kelvin):
        self.calls.append(("written", kelvin))

    async def async_request_refresh(self):
        self.calls.append(("refresh",))


def _entity(light_module, addresses_payload, devices_payload, *, is_on: bool):
    lights = {
        light.device_id: light
        for light in reconcile_lights(addresses_payload, devices_payload)
    }
    group = GroupDevice(
        device_id="0_g_1", channel=0, group_addr=1, kind="dali",
        name="Group", is_on=is_on, stored_level=200 if is_on else 0, min_level=1,
        max_level=254, has_color_temp=True, color_temp_k=3000, user_warm=None, user_cool=None,
        members=("0_s_1", "0_s_21"),
    )
    coordinator = FakeCoordinator(group, lights)
    entity = object.__new__(light_module.ATXLEDGroupLight)
    entity.coordinator = coordinator
    entity.device_id = group.device_id
    return entity, coordinator.calls


async def test_group_turn_on_sends_level_before_kelvin(
    light_module, addresses_payload: dict, devices_payload: dict
) -> None:
    entity, calls = _entity(light_module, addresses_payload, devices_payload, is_on=False)
    await entity.async_turn_on(brightness=255, color_temp_kelvin=2700)
    assert [call[0] for call in calls] == ["level", "kelvin", "written", "refresh"]
    assert calls[1] == ("kelvin", 2700)


async def test_group_turn_on_kelvin_only_restores_level_first_when_off(
    light_module, addresses_payload: dict, devices_payload: dict
) -> None:
    entity, calls = _entity(light_module, addresses_payload, devices_payload, is_on=False)
    await entity.async_turn_on(color_temp_kelvin=2700)
    assert [call[0] for call in calls] == ["level", "kelvin", "written", "refresh"]


async def test_group_turn_on_kelvin_only_when_on_sends_no_level(
    light_module, addresses_payload: dict, devices_payload: dict
) -> None:
    entity, calls = _entity(light_module, addresses_payload, devices_payload, is_on=True)
    await entity.async_turn_on(color_temp_kelvin=2700)
    assert [call[0] for call in calls] == ["kelvin", "written", "refresh"]


async def test_group_turn_on_brightness_only_writes_no_kelvin(
    light_module, addresses_payload: dict, devices_payload: dict
) -> None:
    entity, calls = _entity(light_module, addresses_payload, devices_payload, is_on=True)
    await entity.async_turn_on(brightness=128)
    assert [call[0] for call in calls] == ["level", "refresh"]


async def test_group_turn_on_refreshes_when_kelvin_fails_after_level(
    light_module, addresses_payload: dict, devices_payload: dict
) -> None:
    from atx_led.client import ATXLEDApiError

    entity, calls = _entity(light_module, addresses_payload, devices_payload, is_on=False)

    async def fail(group, lights, kelvin):
        calls.append(("kelvin", kelvin))
        raise ATXLEDApiError("Group has no known color-temperature members")

    entity.coordinator.client.async_set_group_color_temp = fail
    with pytest.raises(sys.modules["homeassistant.exceptions"].HomeAssistantError):
        await entity.async_turn_on(color_temp_kelvin=2700)
    assert [call[0] for call in calls] == ["level", "kelvin", "refresh"]
