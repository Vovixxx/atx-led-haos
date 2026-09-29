"""Hub renames refresh original names without changing user assigned names."""

from __future__ import annotations

from dataclasses import replace
import importlib
import sys
from types import ModuleType, SimpleNamespace

import pytest

from atx_led.models import SceneDevice, reconcile_lights


@pytest.fixture
def entity_modules(monkeypatch: pytest.MonkeyPatch):
    homeassistant = ModuleType("homeassistant")
    homeassistant.__path__ = []
    components = ModuleType("homeassistant.components")
    components.__path__ = []
    light = ModuleType("homeassistant.components.light")
    light.ATTR_BRIGHTNESS = "brightness"
    light.ATTR_COLOR_TEMP_KELVIN = "color_temp_kelvin"
    light.ColorMode = SimpleNamespace(COLOR_TEMP="color_temp", BRIGHTNESS="brightness")
    light.LightEntity = type("LightEntity", (), {})
    scene = ModuleType("homeassistant.components.scene")
    scene.Scene = type("Scene", (), {})
    core = ModuleType("homeassistant.core")
    core.HomeAssistant = type("HomeAssistant", (), {})
    core.callback = lambda fn: fn
    exceptions = ModuleType("homeassistant.exceptions")
    exceptions.HomeAssistantError = type("HomeAssistantError", (Exception,), {})
    helpers = ModuleType("homeassistant.helpers")
    helpers.__path__ = []
    device_registry = ModuleType("homeassistant.helpers.device_registry")
    device_registry.DeviceInfo = dict
    registry = SimpleNamespace(updates=[])

    def update_device(device_id, *, name):
        registry.updates.append((device_id, name))
        registry.entry.name = name
        return registry.entry

    registry.async_update_device = update_device
    device_registry.async_get = lambda _hass: registry
    entity_platform = ModuleType("homeassistant.helpers.entity_platform")
    entity_platform.AddConfigEntryEntitiesCallback = object
    update_coordinator = ModuleType("homeassistant.helpers.update_coordinator")

    class CoordinatorEntity:
        @classmethod
        def __class_getitem__(cls, _item):
            return cls

        def __init__(self, coordinator):
            self.coordinator = coordinator
            self.device_entry = None
            self.hass = object()
            self.update_count = 0

        def _handle_coordinator_update(self):
            self.update_count += 1

    update_coordinator.CoordinatorEntity = CoordinatorEntity
    coordinator_module = ModuleType("atx_led.coordinator")
    coordinator_module.ATXLEDConfigEntry = type("ATXLEDConfigEntry", (), {})
    coordinator_module.ATXLEDCoordinator = type("ATXLEDCoordinator", (), {})
    modules = (
        homeassistant, components, light, scene, core, exceptions, helpers,
        device_registry, entity_platform, update_coordinator, coordinator_module,
    )
    with monkeypatch.context() as patch:
        for module in modules:
            patch.setitem(sys.modules, module.__name__, module)
        sys.modules.pop("atx_led.light", None)
        sys.modules.pop("atx_led.scene", None)
        light_module = importlib.import_module("atx_led.light")
        scene_module = importlib.import_module("atx_led.scene")
        yield light_module, scene_module, registry
        sys.modules.pop("atx_led.light", None)
        sys.modules.pop("atx_led.scene", None)


def test_fixture_hub_rename_updates_device_name_but_keeps_user_name(
    entity_modules, addresses_payload: dict, devices_payload: dict
) -> None:
    light_module, _scene_module, registry = entity_modules
    fixture = next(
        light for light in reconcile_lights(addresses_payload, devices_payload)
        if light.device_id == "0_s_1"
    )
    coordinator = SimpleNamespace(
        hub_id="hub", hub_device_id="hub-device", lights={fixture.device_id: fixture}
    )
    coordinator.get_light = lambda device_id: coordinator.lights.get(device_id)
    entity = light_module.ATXLEDLight(coordinator, fixture.device_id)
    registry.entry = SimpleNamespace(
        id="device-1", name=fixture.name, name_by_user="My Hall Lights"
    )
    entity.device_entry = registry.entry

    coordinator.lights[fixture.device_id] = replace(fixture, name="Renamed Fixture")
    entity._handle_coordinator_update()

    assert registry.updates == [("device-1", "Renamed Fixture")]
    assert entity.device_entry.name == "Renamed Fixture"
    assert entity.device_entry.name_by_user == "My Hall Lights"
    assert entity.update_count == 1
    entity._handle_coordinator_update()
    assert len(registry.updates) == 1


def test_scene_hub_rename_updates_original_name_but_keeps_user_name(entity_modules) -> None:
    _light_module, scene_module, _registry = entity_modules
    scene = SceneDevice(
        scene_id="0_sc_1", name="Original Scene", channel=0,
        dali_scene=1, group_addr=None, members=("0_s_1",),
    )
    coordinator = SimpleNamespace(hub_id="hub", scenes={scene.scene_id: scene})
    coordinator.get_scene = lambda scene_id: coordinator.scenes.get(scene_id)
    entity = scene_module.ATXLEDScene(coordinator, scene.scene_id)
    entity_registry_entry = SimpleNamespace(name="My Evening Scene")
    entity.registry_entry = entity_registry_entry

    coordinator.scenes[scene.scene_id] = replace(scene, name="Renamed Scene")
    entity._handle_coordinator_update()

    assert entity._attr_name == "Renamed Scene"
    assert entity.registry_entry.name == "My Evening Scene"
    assert entity.update_count == 1
