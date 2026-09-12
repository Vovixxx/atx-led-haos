from atx_led.models import (
    apply_group_patches,
    parse_addr_id,
    parse_device,
    preserve_group_live_state,
    reconcile_groups,
    reconcile_lights,
)


def test_group_membership_bitmask_uses_dali_group_bits() -> None:
    device = parse_device(
        "0_s_1",
        {
            "channel": 0,
            "short_addr": 1,
            "dev_name": "Hall Light",
            "groups": 5,
            "is_button": False,
            "is_io_device": False,
            "is_passive": False,
            "is_relay_device": False,
        },
    )
    assert device is not None
    assert device.group_membership == (0, 2)


def test_parse_addr_id_accepts_light_group_and_virtual() -> None:
    assert parse_addr_id("0_s_1") == (0, "s", 1)
    assert parse_addr_id("0_g_1") == (0, "g", 1)
    assert parse_addr_id("0_v_0") == (0, "v", 0)
    assert parse_addr_id("all") is None


def test_reconcile_groups_skips_broadcast_and_creates_dali_and_virtual(
    addresses_payload: dict, devices_payload: dict
) -> None:
    lights = reconcile_lights(addresses_payload, devices_payload)
    groups = reconcile_groups(addresses_payload, devices_payload, lights)
    ids = [group.device_id for group in groups]
    assert ids == ["0_g_1", "0_v_0"]
    assert all(group.device_id != "all" for group in groups)
    dali = next(group for group in groups if group.device_id == "0_g_1")
    virtual = next(group for group in groups if group.device_id == "0_v_0")
    assert dali.is_dali_group is True
    assert dali.is_on is True
    assert dali.stored_level == 128
    assert dali.members == ("0_s_1", "0_s_11")
    assert dali.unique_suffix == "g_0_1"
    assert virtual.is_dali_group is False
    assert virtual.name == "Virtual Group 0"
    assert virtual.unique_suffix == "v_0_0"
    assert virtual.is_on is None


def test_group_members_can_be_inferred_from_fixture_membership(
    addresses_payload: dict, devices_payload: dict
) -> None:
    devices = dict(devices_payload)
    group_raw = dict(devices["0_g_1"])
    group_raw.pop("members")
    devices["0_g_1"] = group_raw
    lights = reconcile_lights(addresses_payload, devices)
    groups = reconcile_groups(addresses_payload, devices, lights)
    dali = next(group for group in groups if group.device_id == "0_g_1")
    assert dali.members == ("0_s_1",)


def test_group_unique_suffix_does_not_collide_with_fixture_suffix(
    addresses_payload: dict, devices_payload: dict
) -> None:
    lights = reconcile_lights(addresses_payload, devices_payload)
    groups = reconcile_groups(addresses_payload, devices_payload, lights)
    light_suffixes = {light.unique_suffix for light in lights}
    group_suffixes = {group.unique_suffix for group in groups}
    assert light_suffixes.isdisjoint(group_suffixes)


def test_group_patch_updates_state_without_dropping_members(
    addresses_payload: dict, devices_payload: dict
) -> None:
    lights = reconcile_lights(addresses_payload, devices_payload)
    groups = {
        group.device_id: group
        for group in reconcile_groups(addresses_payload, devices_payload, lights)
    }
    updated = apply_group_patches(
        groups,
        [("0_g_1", {"dev_on": False, "level": 46, "color_temp_k": 3000})],
    )
    group = updated["0_g_1"]
    assert group.is_on is False
    assert group.stored_level == 46
    assert group.color_temp_k == 3000
    assert group.members == ("0_s_1", "0_s_11")
    assert updated["0_v_0"] is groups["0_v_0"]


def test_group_patches_do_not_create_unknown_groups(
    addresses_payload: dict, devices_payload: dict
) -> None:
    lights = reconcile_lights(addresses_payload, devices_payload)
    groups = {
        group.device_id: group
        for group in reconcile_groups(addresses_payload, devices_payload, lights)
    }
    updated = apply_group_patches(
        groups,
        [
            ("0_g_9", {"dev_on": True, "level": 10}),
            ("0_s_1", {"dev_on": True, "level": 10}),
        ],
    )
    assert set(updated) == set(groups)
    assert "0_g_9" not in updated


def test_http_poll_keeps_websocket_group_state_when_inventory_omits_it(
    addresses_payload: dict, devices_payload: dict
) -> None:
    lights = reconcile_lights(addresses_payload, devices_payload)
    groups = {
        group.device_id: group
        for group in reconcile_groups(addresses_payload, devices_payload, lights)
    }
    live = apply_group_patches(
        groups, [("0_g_1", {"dev_on": False, "level": 46}), ("0_v_0", {"dev_on": True, "level": 80})]
    )
    address_only = dict(devices_payload)
    address_only.pop("0_g_1")
    rediscovered = {
        group.device_id: group
        for group in reconcile_groups(addresses_payload, address_only, lights)
    }
    merged = preserve_group_live_state(live, rediscovered)
    assert merged["0_g_1"].is_on is False
    assert merged["0_g_1"].stored_level == 46
    assert merged["0_v_0"].is_on is True
    assert merged["0_v_0"].stored_level == 80
