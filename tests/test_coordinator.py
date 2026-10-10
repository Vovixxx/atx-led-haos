"""Coordinator push updates must not change the inventory poll deadline."""

from __future__ import annotations

import asyncio
import importlib
import sys
import types
from typing import Generic, TypeVar

import pytest

from atx_led.client import ATXLEDApiError
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
    coordinator._init_write_state()

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


# --- one-call turn-on: written-colour map, immediate state, queue ---------------------


class FakeClient:
    def __init__(self) -> None:
        self.sent: list[tuple[int, list[str]]] = []
        self.queries: list[tuple[int, int]] = []
        self.mirek_by_addr: dict[int, int | None] = {}
        self.fail = False
        self.gate: asyncio.Event | None = None
        self.entered = asyncio.Event()

    async def async_send_raw(self, channel, commands):
        self.entered.set()
        if self.gate is not None:
            await self.gate.wait()
        if self.fail:
            raise ATXLEDApiError("Hub rejected the DALI command")
        self.sent.append((channel, list(commands)))

    async def async_query_color_mirek(self, channel, short_addr):
        self.queries.append((channel, short_addr))
        if short_addr not in self.mirek_by_addr:
            raise ATXLEDApiError("Hub rejected the DALI command")
        return self.mirek_by_addr[short_addr]


def _make(coordinator_module, addresses_payload, devices_payload, group_kind="dali"):
    coordinator = object.__new__(coordinator_module.ATXLEDCoordinator)
    lights = {
        light.device_id: light
        for light in reconcile_lights(addresses_payload, devices_payload)
    }
    group = GroupDevice(
        device_id="0_g_6" if group_kind == "dali" else "0_v_0", channel=0,
        group_addr=6 if group_kind == "dali" else 0, kind=group_kind,
        name="Group", is_on=False, stored_level=0, min_level=1, max_level=254,
        has_color_temp=True, color_temp_k=None, user_warm=370, user_cool=154,
        members=("0_s_1", "0_s_21"),
    )
    coordinator.data = coordinator_module.ATXLEDData(
        lights=lights, groups={group.device_id: group}, scenes={}
    )
    coordinator.notifications = []
    coordinator.client = FakeClient()
    coordinator.config_entry = types.SimpleNamespace(options={})
    coordinator._init_write_state()
    return coordinator, group


async def test_light_write_is_one_send_raw_and_shows_intended_state(
    coordinator_module, addresses_payload, devices_payload
) -> None:
    coordinator, _group = _make(coordinator_module, addresses_payload, devices_payload)
    await coordinator.async_set_light("0_s_1", 250, 4000)
    assert coordinator.client.sent == [
        (0, ["hA3FA", "hC300", "hC108", "h03E7", "h02FA"])
    ]
    light = coordinator.data.lights["0_s_1"]
    assert (light.is_on, light.stored_level, light.color_temp_k) == (True, 250, 4000)
    assert len(coordinator.notifications) == 1


async def test_second_write_with_same_colour_is_a_single_dapc(
    coordinator_module, addresses_payload, devices_payload
) -> None:
    coordinator, _group = _make(coordinator_module, addresses_payload, devices_payload)
    await coordinator.async_set_light("0_s_1", 250, 4000)
    await coordinator.async_set_light("0_s_1", 100, 4000)
    assert coordinator.client.sent[1] == (0, ["h0264"])


async def test_group_write_records_colour_on_members_and_group(
    coordinator_module, addresses_payload, devices_payload
) -> None:
    coordinator, group = _make(coordinator_module, addresses_payload, devices_payload)
    await coordinator.async_set_group(group.device_id, 253, 2700)
    assert coordinator.client.sent == [
        (0, ["hA372", "hC301", "hC108", "h8DE7", "h8CFD"])
    ]
    assert coordinator.colors == {"0_s_1": 2703, "0_s_21": 2703}
    shown = coordinator.data.groups[group.device_id]
    assert (shown.is_on, shown.stored_level, shown.color_temp_k) == (True, 253, 2703)
    assert coordinator.data.lights["0_s_21"].is_on is True


async def test_group_shows_colour_only_while_members_agree(
    coordinator_module, addresses_payload, devices_payload
) -> None:
    coordinator, group = _make(coordinator_module, addresses_payload, devices_payload)
    await coordinator.async_set_group(group.device_id, 253, 4000)
    await coordinator.async_set_light("0_s_1", 253, 3500)
    assert coordinator.data.groups[group.device_id].color_temp_k is None
    await coordinator.async_set_light("0_s_21", 253, 3500)
    assert coordinator.data.groups[group.device_id].color_temp_k == 3500


async def test_virtual_group_write_sends_one_call_per_channel(
    coordinator_module, addresses_payload, devices_payload
) -> None:
    coordinator, group = _make(
        coordinator_module, addresses_payload, devices_payload, group_kind="virtual"
    )
    await coordinator.async_set_group(group.device_id, 200, None)
    assert coordinator.client.sent == [(0, ["h02C8", "h2AC8"])]


async def test_written_colour_beats_stale_hub_colour_in_ws_patch(
    coordinator_module, addresses_payload, devices_payload
) -> None:
    coordinator, _group = _make(coordinator_module, addresses_payload, devices_payload)
    await coordinator.async_set_light("0_s_1", 250, 4000)
    coordinator._handle_ws_message(
        "devices", [{"addr": "0_s_1", "data": {"color_temp_k": 3500, "level": 90}}]
    )
    light = coordinator.data.lights["0_s_1"]
    assert light.color_temp_k == 4000
    assert light.stored_level == 90  # level still comes from the hub


async def test_hub_colour_is_ignored_for_a_fixture_never_written(
    coordinator_module, addresses_payload, devices_payload
) -> None:
    coordinator, _group = _make(coordinator_module, addresses_payload, devices_payload)
    coordinator._handle_ws_message(
        "devices", [{"addr": "0_s_1", "data": {"color_temp_k": 3500}}]
    )
    assert coordinator.data.lights["0_s_1"].color_temp_k is None


async def test_poll_keeps_written_colour_over_hub_record(
    coordinator_module, addresses_payload, devices_payload
) -> None:
    coordinator, _group = _make(coordinator_module, addresses_payload, devices_payload)
    await coordinator.async_set_light("0_s_1", 250, 4000)
    inventory = _inventory(addresses_payload, devices_payload)
    coordinator.client.async_discover_inventory = _fixed(inventory)
    data = await coordinator._async_update_data()
    assert data.lights["0_s_1"].color_temp_k == 4000
    assert data.lights["0_s_21"].color_temp_k is None


def _inventory(addresses_payload, devices_payload):
    from atx_led.models import reconcile_groups

    lights = reconcile_lights(addresses_payload, devices_payload)
    return lights, reconcile_groups(addresses_payload, devices_payload, lights), []


def _fixed(inventory):
    async def discover():
        return inventory

    return discover


async def test_poll_that_started_before_a_write_cannot_overwrite_it(
    coordinator_module, addresses_payload, devices_payload
) -> None:
    coordinator, _group = _make(coordinator_module, addresses_payload, devices_payload)
    inventory = _inventory(addresses_payload, devices_payload)  # 0_s_1 is off, level 185

    async def discover():
        await coordinator.async_set_light("0_s_1", 250, None)  # write lands mid-poll
        return inventory

    coordinator.client.async_discover_inventory = discover
    data = await coordinator._async_update_data()
    assert (data.lights["0_s_1"].is_on, data.lights["0_s_1"].stored_level) == (True, 250)

    # the next poll starts after the write, so hub data wins again
    coordinator.data = data
    coordinator.client.async_discover_inventory = _fixed(inventory)
    later = await coordinator._async_update_data()
    assert later.lights["0_s_1"].is_on is False


async def test_failed_write_leaves_colour_map_and_state_unchanged(
    coordinator_module, addresses_payload, devices_payload
) -> None:
    coordinator, _group = _make(coordinator_module, addresses_payload, devices_payload)
    await coordinator.async_set_light("0_s_1", 250, 4000)
    coordinator.client.fail = True
    with pytest.raises(ATXLEDApiError):
        await coordinator.async_set_light("0_s_1", 100, 3000)
    assert coordinator.colors == {"0_s_1": 4000}
    assert coordinator.data.lights["0_s_1"].stored_level == 250
    assert coordinator.intended_on("0_s_1") is None


def test_restore_fills_only_unknown_colours(
    coordinator_module, addresses_payload, devices_payload
) -> None:
    coordinator, _group = _make(coordinator_module, addresses_payload, devices_payload)
    coordinator.async_restore_color("0_s_1", 3500)
    coordinator.async_restore_color("0_s_1", 5000)
    assert coordinator.colors == {"0_s_1": 3500}
    assert coordinator.data.lights["0_s_1"].color_temp_k == 3500


async def test_startup_read_queries_each_unknown_colour_fixture_from_the_driver(
    coordinator_module, addresses_payload, devices_payload
) -> None:
    coordinator, _group = _make(coordinator_module, addresses_payload, devices_payload)
    coordinator.async_restore_color("0_s_21", 3500)
    coordinator.client.mirek_by_addr = {1: 370}
    await coordinator.async_read_missing_colors()
    assert coordinator.client.queries == [(0, 1)]  # 0_s_11 has no colour, 0_s_21 restored
    assert coordinator.colors == {"0_s_21": 3500, "0_s_1": 2703}


async def test_startup_read_failure_leaves_colour_unknown(
    coordinator_module, addresses_payload, devices_payload
) -> None:
    coordinator, _group = _make(coordinator_module, addresses_payload, devices_payload)
    coordinator.client.mirek_by_addr = {1: None}  # no answer; addr 21 raises
    await coordinator.async_read_missing_colors()
    assert coordinator.colors == {}
    assert coordinator.data.lights["0_s_1"].color_temp_k is None


async def test_latest_waiting_command_wins_and_in_flight_completes(
    coordinator_module, addresses_payload, devices_payload
) -> None:
    coordinator, _group = _make(coordinator_module, addresses_payload, devices_payload)
    coordinator.client.gate = asyncio.Event()
    first = asyncio.create_task(coordinator.async_set_light("0_s_1", 100, None))
    await coordinator.client.entered.wait()
    second = asyncio.create_task(coordinator.async_set_light("0_s_1", 150, None))
    third = asyncio.create_task(coordinator.async_set_light("0_s_1", 200, None))
    await asyncio.sleep(0)
    coordinator.client.gate.set()
    await asyncio.gather(first, second, third)
    assert [frames for _channel, frames in coordinator.client.sent] == [["h0264"], ["h02C8"]]
    assert coordinator.intended_on("0_s_1") is None


async def test_queued_commands_for_other_targets_do_not_replace_each_other(
    coordinator_module, addresses_payload, devices_payload
) -> None:
    coordinator, _group = _make(coordinator_module, addresses_payload, devices_payload)
    await asyncio.gather(
        coordinator.async_set_light("0_s_1", 100, None),
        coordinator.async_set_light("0_s_21", 100, None),
    )
    assert len(coordinator.client.sent) == 2


async def test_intended_state_follows_the_newest_press_while_sending(
    coordinator_module, addresses_payload, devices_payload
) -> None:
    coordinator, _group = _make(coordinator_module, addresses_payload, devices_payload)
    coordinator.client.gate = asyncio.Event()
    on = asyncio.create_task(coordinator.async_set_light("0_s_1", 200, None))
    await coordinator.client.entered.wait()
    assert coordinator.intended_on("0_s_1") is True
    off = asyncio.create_task(coordinator.async_set_light("0_s_1", 0, None))
    await asyncio.sleep(0)
    assert coordinator.intended_on("0_s_1") is False
    coordinator.client.gate.set()
    await asyncio.gather(on, off)
    assert [frames for _channel, frames in coordinator.client.sent] == [["h02C8"], ["h0200"]]
    assert coordinator.data.lights["0_s_1"].is_on is False


async def test_cancelled_waiting_press_is_dropped_and_queue_survives(
    coordinator_module, addresses_payload, devices_payload
) -> None:
    coordinator, _group = _make(coordinator_module, addresses_payload, devices_payload)
    coordinator.client.gate = asyncio.Event()
    first = asyncio.create_task(coordinator.async_set_light("0_s_1", 100, None))
    await coordinator.client.entered.wait()
    waiting = asyncio.create_task(coordinator.async_set_light("0_s_1", 150, None))
    await asyncio.sleep(0)
    waiting.cancel()
    await asyncio.sleep(0)
    coordinator.client.gate.set()
    await first
    assert [f for _c, f in coordinator.client.sent] == [["h0264"]]
    await coordinator.async_set_light("0_s_1", 200, None)  # queue still works
    assert [f for _c, f in coordinator.client.sent][-1] == ["h02C8"]


async def test_cancelled_in_flight_caller_does_not_lose_the_waiting_press(
    coordinator_module, addresses_payload, devices_payload
) -> None:
    coordinator, _group = _make(coordinator_module, addresses_payload, devices_payload)
    coordinator.client.gate = asyncio.Event()
    on = asyncio.create_task(coordinator.async_set_light("0_s_1", 200, None))
    await coordinator.client.entered.wait()
    off = asyncio.create_task(coordinator.async_set_light("0_s_1", 0, None))
    await asyncio.sleep(0)
    on.cancel()
    await asyncio.sleep(0)
    coordinator.client.gate.set()
    await off
    assert [f for _c, f in coordinator.client.sent] == [["h02C8"], ["h0200"]]
    assert coordinator.intended_on("0_s_1") is None


async def test_restore_beats_a_startup_driver_read_but_not_a_write(
    coordinator_module, addresses_payload, devices_payload
) -> None:
    coordinator, _group = _make(coordinator_module, addresses_payload, devices_payload)
    coordinator.client.mirek_by_addr = {1: 250, 21: 250}
    await coordinator.async_read_missing_colors()
    assert coordinator.colors["0_s_1"] == 4000
    coordinator.async_restore_color("0_s_1", 3500)
    assert coordinator.colors["0_s_1"] == 3500
    await coordinator.async_set_light("0_s_21", 200, 3000)
    coordinator.async_restore_color("0_s_21", 5000)
    assert coordinator.colors["0_s_21"] == 3003
