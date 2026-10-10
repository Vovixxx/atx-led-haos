"""Light and group turn-on hand one (level, Kelvin) call to the coordinator."""

from __future__ import annotations

from dataclasses import replace
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
    restore_state = module("homeassistant.helpers.restore_state")

    class RestoreEntity:
        async def async_get_last_state(self):
            return self.last_state

        async def async_added_to_hass(self) -> None:
            return None

    restore_state.RestoreEntity = RestoreEntity
    update_coordinator = module("homeassistant.helpers.update_coordinator")
    update_coordinator.CoordinatorEntity = CoordinatorEntity
    update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
    update_coordinator.UpdateFailed = type("UpdateFailed", (Exception,), {})
    modules = (
        homeassistant, components, light, config_entries, const, core, exceptions,
        helpers, device_registry, entity_platform, restore_state, update_coordinator,
    )
    with monkeypatch.context() as patch:
        for mod in modules:
            patch.setitem(sys.modules, mod.__name__, mod)
        for name in ("atx_led.light", "atx_led.coordinator"):
            sys.modules.pop(name, None)
        yield importlib.import_module("atx_led.light")
        for name in ("atx_led.light", "atx_led.coordinator"):
            sys.modules.pop(name, None)


class FakeCoordinator:
    def __init__(self, group: GroupDevice, lights: dict) -> None:
        self.calls: list = []
        self.data = types.SimpleNamespace(lights=lights, groups={group.device_id: group})
        self._group = group
        self.intent: dict = {}
        self.error: Exception | None = None

    def get_group(self, device_id):
        return self._group

    def get_light(self, device_id):
        return self.data.lights.get(device_id)

    def intended_on(self, target_id):
        return self.intent.get(target_id)

    def async_restore_color(self, device_id, kelvin):
        self.calls.append(("restore", device_id, kelvin))

    async def async_set_group(self, group_id, level, kelvin=None):
        self.calls.append(("group", group_id, level, kelvin))
        if self.error:
            raise self.error

    async def async_set_light(self, device_id, level, kelvin=None):
        self.calls.append(("light", device_id, level, kelvin))
        if self.error:
            raise self.error

    async def async_request_refresh(self):
        self.calls.append(("refresh",))


def _group_entity(light_module, addresses_payload, devices_payload, *, is_on: bool):
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
    return entity, coordinator


def _light_entity(light_module, addresses_payload, devices_payload, device_id, *, is_on: bool):
    lights = {
        light.device_id: replace(light, is_on=is_on, stored_level=185 if is_on else 0)
        for light in reconcile_lights(addresses_payload, devices_payload)
    }
    group = GroupDevice(
        device_id="0_g_1", channel=0, group_addr=1, kind="dali", name="G", is_on=False,
        stored_level=0, min_level=1, max_level=254, has_color_temp=False, color_temp_k=None,
        user_warm=None, user_cool=None, members=(),
    )
    coordinator = FakeCoordinator(group, lights)
    entity = object.__new__(light_module.ATXLEDLight)
    entity.coordinator = coordinator
    entity.device_id = device_id
    return entity, coordinator


async def test_group_turn_on_is_one_coordinator_call_with_level_and_kelvin(
    light_module, addresses_payload: dict, devices_payload: dict
) -> None:
    entity, coordinator = _group_entity(light_module, addresses_payload, devices_payload, is_on=False)
    await entity.async_turn_on(brightness=255, color_temp_kelvin=2700)
    assert coordinator.calls == [("group", "0_g_1", 254, 2700)]


async def test_group_turn_on_kelvin_only_restores_level_when_off(
    light_module, addresses_payload: dict, devices_payload: dict
) -> None:
    entity, coordinator = _group_entity(light_module, addresses_payload, devices_payload, is_on=False)
    await entity.async_turn_on(color_temp_kelvin=2700)
    assert coordinator.calls == [("group", "0_g_1", 254, 2700)]


async def test_group_turn_on_kelvin_only_when_on_keeps_current_level(
    light_module, addresses_payload: dict, devices_payload: dict
) -> None:
    entity, coordinator = _group_entity(light_module, addresses_payload, devices_payload, is_on=True)
    await entity.async_turn_on(color_temp_kelvin=2700)
    assert coordinator.calls == [("group", "0_g_1", None, 2700)]


async def test_group_turn_on_from_off_without_args_uses_restore_level(
    light_module, addresses_payload: dict, devices_payload: dict
) -> None:
    entity, coordinator = _group_entity(light_module, addresses_payload, devices_payload, is_on=False)
    await entity.async_turn_on()
    assert coordinator.calls == [("group", "0_g_1", 254, None)]


async def test_group_turn_on_brightness_only_sends_no_kelvin(
    light_module, addresses_payload: dict, devices_payload: dict
) -> None:
    entity, coordinator = _group_entity(light_module, addresses_payload, devices_payload, is_on=True)
    await entity.async_turn_on(brightness=128)
    assert coordinator.calls == [("group", "0_g_1", 128, None)]


async def test_group_without_colour_members_ignores_kelvin(
    light_module, addresses_payload: dict, devices_payload: dict
) -> None:
    entity, coordinator = _group_entity(light_module, addresses_payload, devices_payload, is_on=True)
    coordinator._group = replace(coordinator._group, has_color_temp=False)
    await entity.async_turn_on(brightness=128, color_temp_kelvin=2700)
    assert coordinator.calls == [("group", "0_g_1", 128, None)]


async def test_group_turn_off_is_level_zero(
    light_module, addresses_payload: dict, devices_payload: dict
) -> None:
    entity, coordinator = _group_entity(light_module, addresses_payload, devices_payload, is_on=True)
    await entity.async_turn_off()
    assert coordinator.calls == [("group", "0_g_1", 0, None)]


async def test_group_failure_raises_and_refreshes_level_from_hub(
    light_module, addresses_payload: dict, devices_payload: dict
) -> None:
    from atx_led.client import ATXLEDApiError

    entity, coordinator = _group_entity(light_module, addresses_payload, devices_payload, is_on=False)
    coordinator.error = ATXLEDApiError("Hub rejected the DALI command")
    with pytest.raises(sys.modules["homeassistant.exceptions"].HomeAssistantError):
        await entity.async_turn_on(color_temp_kelvin=2700)
    assert coordinator.calls == [("group", "0_g_1", 254, 2700), ("refresh",)]


async def test_group_toggle_reads_the_intended_state(
    light_module, addresses_payload: dict, devices_payload: dict
) -> None:
    entity, coordinator = _group_entity(light_module, addresses_payload, devices_payload, is_on=False)
    await entity.async_toggle()
    coordinator.intent["0_g_1"] = True  # first press still being sent
    await entity.async_toggle()
    assert coordinator.calls == [("group", "0_g_1", 254, None), ("group", "0_g_1", 0, None)]


async def test_light_turn_on_with_brightness_and_kelvin_is_one_call(
    light_module, addresses_payload: dict, devices_payload: dict
) -> None:
    entity, coordinator = _light_entity(
        light_module, addresses_payload, devices_payload, "0_s_1", is_on=False
    )
    await entity.async_turn_on(brightness=255, color_temp_kelvin=4000)
    assert coordinator.calls == [("light", "0_s_1", 250, 4000)]


async def test_light_turn_on_from_off_restores_stored_level(
    light_module, addresses_payload: dict, devices_payload: dict
) -> None:
    entity, coordinator = _light_entity(
        light_module, addresses_payload, devices_payload, "0_s_1", is_on=False
    )
    coordinator.data.lights["0_s_1"] = replace(coordinator.data.lights["0_s_1"], stored_level=120)
    await entity.async_turn_on()
    assert coordinator.calls == [("light", "0_s_1", 120, None)]


async def test_light_dim_while_on_uses_the_same_call(
    light_module, addresses_payload: dict, devices_payload: dict
) -> None:
    entity, coordinator = _light_entity(
        light_module, addresses_payload, devices_payload, "0_s_1", is_on=True
    )
    await entity.async_turn_on(brightness=128)
    assert coordinator.calls == [("light", "0_s_1", 150, None)]


async def test_light_without_colour_support_ignores_kelvin(
    light_module, addresses_payload: dict, devices_payload: dict
) -> None:
    entity, coordinator = _light_entity(
        light_module, addresses_payload, devices_payload, "0_s_11", is_on=True
    )
    await entity.async_turn_on(brightness=100, color_temp_kelvin=4000)
    assert coordinator.calls == [("light", "0_s_11", 100, None)]


async def test_light_colour_only_while_on_keeps_level(
    light_module, addresses_payload: dict, devices_payload: dict
) -> None:
    entity, coordinator = _light_entity(
        light_module, addresses_payload, devices_payload, "0_s_1", is_on=True
    )
    await entity.async_turn_on(color_temp_kelvin=4000)
    assert coordinator.calls == [("light", "0_s_1", None, 4000)]


async def test_light_turn_on_while_on_with_nothing_to_change_sends_nothing(
    light_module, addresses_payload: dict, devices_payload: dict
) -> None:
    entity, coordinator = _light_entity(
        light_module, addresses_payload, devices_payload, "0_s_1", is_on=True
    )
    await entity.async_turn_on()
    assert coordinator.calls == []


async def test_light_turn_off_and_double_press_toggle(
    light_module, addresses_payload: dict, devices_payload: dict
) -> None:
    entity, coordinator = _light_entity(
        light_module, addresses_payload, devices_payload, "0_s_1", is_on=False
    )
    await entity.async_turn_off()
    await entity.async_toggle()  # hub still says off, nothing pending: toggles on
    coordinator.intent["0_s_1"] = True
    await entity.async_toggle()  # first press still in flight: second press is off
    assert coordinator.calls == [
        ("light", "0_s_1", 0, None),
        ("light", "0_s_1", 250, None),
        ("light", "0_s_1", 0, None),
    ]


async def test_light_failure_raises_and_refreshes(
    light_module, addresses_payload: dict, devices_payload: dict
) -> None:
    from atx_led.client import ATXLEDConnectionError

    entity, coordinator = _light_entity(
        light_module, addresses_payload, devices_payload, "0_s_1", is_on=False
    )
    coordinator.error = ATXLEDConnectionError("timeout")
    with pytest.raises(sys.modules["homeassistant.exceptions"].HomeAssistantError):
        await entity.async_turn_on(brightness=100)
    assert coordinator.calls[-1] == ("refresh",)


async def test_light_restores_last_colour_from_state_attribute(
    light_module, addresses_payload: dict, devices_payload: dict
) -> None:
    entity, coordinator = _light_entity(
        light_module, addresses_payload, devices_payload, "0_s_1", is_on=False
    )
    entity.last_state = types.SimpleNamespace(attributes={"dali_color_temp_kelvin": 3500})
    await entity.async_added_to_hass()
    assert coordinator.calls == [("restore", "0_s_1", 3500)]


async def test_light_restore_without_a_previous_state_does_nothing(
    light_module, addresses_payload: dict, devices_payload: dict
) -> None:
    entity, coordinator = _light_entity(
        light_module, addresses_payload, devices_payload, "0_s_1", is_on=False
    )
    entity.last_state = None
    await entity.async_added_to_hass()
    assert coordinator.calls == []


def test_light_state_attributes_carry_the_remembered_colour(
    light_module, addresses_payload: dict, devices_payload: dict
) -> None:
    entity, coordinator = _light_entity(
        light_module, addresses_payload, devices_payload, "0_s_1", is_on=False
    )
    coordinator.data.lights["0_s_1"] = replace(coordinator.data.lights["0_s_1"], color_temp_k=3500)
    assert entity.extra_state_attributes["dali_color_temp_kelvin"] == 3500
