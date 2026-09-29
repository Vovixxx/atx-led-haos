"""Coordinator push updates must not change the inventory poll deadline."""

from __future__ import annotations

import importlib
import sys
import types
from typing import Generic, TypeVar

import pytest

from atx_led.models import GroupDevice, reconcile_lights


@pytest.fixture
def coordinator_module(monkeypatch: pytest.MonkeyPatch):
    """Load the coordinator with a small stand-in for unavailable HA modules."""
    homeassistant = types.ModuleType("homeassistant")
    homeassistant.__path__ = []
    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = type("ConfigEntry", (), {"__class_getitem__": classmethod(lambda cls, _: cls)})
    const = types.ModuleType("homeassistant.const")
    const.CONF_HOST = "host"
    const.EVENT_HOMEASSISTANT_STOP = "stop"
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = type("HomeAssistant", (), {})
    helpers = types.ModuleType("homeassistant.helpers")
    helpers.__path__ = []
    update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")

    data_type = TypeVar("data_type")

    class DataUpdateCoordinator(Generic[data_type]):
        def async_set_updated_data(self, data):
            self.data = data
            self.poll_due_at = self.now + 15
            self.async_update_listeners()

        def async_update_listeners(self):
            self.notifications.append(self.data)

    update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
    update_coordinator.UpdateFailed = type("UpdateFailed", (Exception,), {})
    modules = {
        module.__name__: module
        for module in (
            homeassistant,
            config_entries,
            const,
            core,
            helpers,
            update_coordinator,
        )
    }
    with monkeypatch.context() as patch:
        for name, module in modules.items():
            patch.setitem(sys.modules, name, module)
        sys.modules.pop("atx_led.coordinator", None)
        module = importlib.import_module("atx_led.coordinator")
        yield module
        sys.modules.pop("atx_led.coordinator", None)


def test_frequent_ws_updates_do_not_postpone_inventory_poll(
    coordinator_module, addresses_payload: dict, devices_payload: dict
) -> None:
    coordinator = object.__new__(coordinator_module.ATXLEDCoordinator)
    lights = {
        light.device_id: light
        for light in reconcile_lights(addresses_payload, devices_payload)
    }
    group = GroupDevice(
        device_id="0_g_1", channel=0, group_addr=1, kind="dali",
        name="Group", is_on=False, stored_level=0, min_level=0,
        max_level=254, has_color_temp=False, color_temp_k=None,
        user_warm=None, user_cool=None, members=(),
    )
    coordinator.data = coordinator_module.ATXLEDData(
        lights=lights, groups={group.device_id: group}, scenes={}
    )
    coordinator.poll_due_at = 15
    coordinator.notifications = []

    for second in range(1, 21):
        coordinator.now = second
        kind = "groups" if second % 2 == 0 else "devices"
        address = group.device_id if kind == "groups" else "0_s_1"
        coordinator._handle_ws_message(
            kind, [{"addr": address, "data": {"level": second}}]
        )
        assert coordinator.poll_due_at == 15

    assert len(coordinator.notifications) == 20
    assert coordinator.data.lights["0_s_1"].stored_level == 19
    assert coordinator.data.groups[group.device_id].stored_level == 20


def test_successful_group_color_temp_write_updates_data_without_resetting_poll(
    coordinator_module,
) -> None:
    coordinator = object.__new__(coordinator_module.ATXLEDCoordinator)
    group = GroupDevice(
        device_id="0_g_1", channel=0, group_addr=1, kind="dali",
        name="Group", is_on=True, stored_level=100, min_level=0,
        max_level=254, has_color_temp=True, color_temp_k=3000,
        user_warm=None, user_cool=None, members=("0_s_1",),
        color_temp_source="hub",
    )
    coordinator.data = coordinator_module.ATXLEDData(
        lights={}, groups={group.device_id: group}, scenes={}
    )
    coordinator.poll_due_at = 15
    coordinator.notifications = []

    coordinator.async_group_color_temp_written(group.device_id, 5000)

    assert coordinator.data.groups[group.device_id].color_temp_k == 5000
    assert coordinator.data.groups[group.device_id].color_temp_source == "derived"
    assert len(coordinator.notifications) == 1
    assert coordinator.poll_due_at == 15
