from atx_led.models import (
    apply_derived_group_states,
    apply_device_patches,
    apply_group_patches,
    color_temp_range_kelvin,
    merge_group_records,
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


def test_group_prefers_hue_name_over_generic_dev_name() -> None:
    addresses = {"Groups": [{"key": "0_g_5", "value": "Group 5"}], "Virtual Groups": []}
    devices = {
        "0_g_5": {
            "address": [0, "group", 5],
            "channel": 0,
            "dev_name": "Group 5",
            "hue_name": "Kitchen Spots",
            "dev_on": False,
            "level": 0,
            "device_ids": [21, 22],
        }
    }
    groups = reconcile_groups(addresses, devices, [])
    assert groups[0].name == "Kitchen Spots"


def test_group_name_falls_back_when_hue_name_missing() -> None:
    addresses = {"Groups": [{"key": "0_g_1", "value": "Dining"}], "Virtual Groups": []}
    devices = {
        "0_g_1": {
            "address": [0, "group", 1],
            "channel": 0,
            "dev_name": "Group 1",
            "hue_name": None,
            "dev_on": False,
            "level": 0,
        }
    }
    groups = reconcile_groups(addresses, devices, [])
    assert groups[0].name == "Group 1"


def test_groups_api_device_ids_become_member_lights_and_keep_hub_state() -> None:
    addresses = {
        "Groups": [{"key": "0_g_5", "value": "Group 5"}],
        "Lights": [{"key": "0_s_21", "value": "Spot 21"}],
        "Virtual Groups": [],
    }
    devices = {
        "0_s_21": {
            "channel": 0,
            "short_addr": 21,
            "dev_name": "Spot 21",
            "dev_on": False,
            "groups": [5],
            "has_color_temp": True,
            "user_warm": 370,
            "user_cool": 200,
            "level": 80,
            "min_level": 50,
            "max_level": 250,
            "is_button": False,
            "is_io_device": False,
            "is_passive": False,
            "is_relay_device": False,
        }
    }
    groups_api = {
        "0_g_5": {
            "address": [0, "group", 5],
            "channel": 0,
            "color_temp_k": 4000,
            "dev_name": "Group 5",
            "dev_on": False,
            "device_ids": [21],
            "device_names": ["Spot 21"],
            "group_id": 5,
            "hue_name": "Kitchen Spots",
            "level": 0,
        }
    }
    merged = merge_group_records(devices, groups_api)
    lights = reconcile_lights(addresses, merged)
    groups = reconcile_groups(addresses, merged, lights)
    group = groups[0]
    assert group.name == "Kitchen Spots"
    assert group.is_on is False
    assert group.stored_level == 0
    assert group.members == ("0_s_21",)
    assert group.state_source == "hub"


def test_address_only_group_derives_state_from_member_lights(
    addresses_payload: dict, devices_payload: dict
) -> None:
    devices = dict(devices_payload)
    devices.pop("0_g_1")
    hall = dict(devices["0_s_1"])
    hall["dev_on"] = True
    hall["groups"] = ["0_g_5"]
    devices["0_s_1"] = hall
    cabinet = dict(devices["0_s_11"])
    cabinet["dev_on"] = False
    cabinet["groups"] = ["0_g_5"]
    devices["0_s_11"] = cabinet
    addresses = dict(addresses_payload)
    addresses["Groups"] = [{"key": "0_g_5", "value": "Group 5"}]
    lights = reconcile_lights(addresses, devices)
    groups = reconcile_groups(addresses, devices, lights)
    group = next(item for item in groups if item.device_id == "0_g_5")
    assert group.is_on is True
    assert group.stored_level == 185
    assert group.members == ("0_s_1", "0_s_11")
    assert group.state_source == "derived"


def test_hub_group_state_is_not_overwritten_by_members(
    addresses_payload: dict, devices_payload: dict
) -> None:
    lights = reconcile_lights(addresses_payload, devices_payload)
    groups = {
        group.device_id: group
        for group in reconcile_groups(addresses_payload, devices_payload, lights)
    }
    derived = apply_derived_group_states(groups, {light.device_id: light for light in lights})
    assert derived["0_g_1"].is_on is True
    assert derived["0_g_1"].stored_level == 128
    assert derived["0_g_1"].state_source == "hub"


def test_fixture_patch_refreshes_derived_group(
    addresses_payload: dict, devices_payload: dict
) -> None:
    devices = dict(devices_payload)
    devices.pop("0_g_1")
    hall = dict(devices["0_s_1"])
    hall["dev_on"] = False
    hall["groups"] = [5]
    devices["0_s_1"] = hall
    addresses = dict(addresses_payload)
    addresses["Groups"] = [{"key": "0_g_5", "value": "Group 5"}]
    lights = {light.device_id: light for light in reconcile_lights(addresses, devices)}
    groups = {
        group.device_id: group
        for group in reconcile_groups(addresses, devices, list(lights.values()))
    }
    assert groups["0_g_5"].is_on is False
    lights = apply_device_patches(lights, [("0_s_1", {"dev_on": True, "level": 90})])
    updated = apply_derived_group_states(groups, lights)
    assert updated["0_g_5"].is_on is True
    assert updated["0_g_5"].stored_level == 90


def test_member_patch_updates_group_even_when_hub_last_said_off(
    addresses_payload: dict, devices_payload: dict
) -> None:
    lights = {light.device_id: light for light in reconcile_lights(addresses_payload, devices_payload)}
    groups = {
        group.device_id: group
        for group in reconcile_groups(addresses_payload, devices_payload, list(lights.values()))
    }
    groups = apply_group_patches(groups, [("0_g_1", {"dev_on": False, "level": 0})])
    assert groups["0_g_1"].state_source == "hub"
    lights = apply_device_patches(lights, [("0_s_1", {"dev_on": True, "level": 90})])
    updated = apply_derived_group_states(groups, lights)
    assert updated["0_g_1"].is_on is True
    assert updated["0_g_1"].stored_level == 90


def test_group_color_temp_is_derived_from_member_capabilities() -> None:
    addresses = {
        "Groups": [{"key": "0_g_5", "value": "Group 5"}],
        "Lights": [
            {"key": "0_s_21", "value": "Spot 21"},
            {"key": "0_s_22", "value": "Spot 22"},
        ],
        "Virtual Groups": [],
    }
    devices = {
        "0_s_21": {
            "channel": 0,
            "short_addr": 21,
            "dev_name": "Spot 21",
            "dev_on": False,
            "groups": [5],
            "has_color_temp": True,
            "color_temp_k": 3875,
            "user_warm": 370,
            "user_cool": 200,
            "level": 80,
            "min_level": 50,
            "max_level": 250,
            "is_button": False,
            "is_io_device": False,
            "is_passive": False,
            "is_relay_device": False,
        },
        "0_s_22": {
            "channel": 0,
            "short_addr": 22,
            "dev_name": "Spot 22",
            "dev_on": False,
            "groups": [5],
            "has_color_temp": True,
            "color_temp_k": 3000,
            "user_warm": 333,
            "user_cool": 154,
            "level": 80,
            "min_level": 50,
            "max_level": 250,
            "is_button": False,
            "is_io_device": False,
            "is_passive": False,
            "is_relay_device": False,
        },
        "0_g_5": {
            "address": [0, "group", 5],
            "channel": 0,
            "dev_name": "Group 5",
            "color_temp_k": 4000,
            "dev_on": False,
            "level": 0,
            "device_ids": [21, 22],
        },
    }
    lights = reconcile_lights(addresses, devices)
    group = reconcile_groups(addresses, devices, lights)[0]
    assert group.has_color_temp is True
    assert group.color_temp_k == 4000
    minimum, maximum = color_temp_range_kelvin(group.user_warm, group.user_cool)
    assert minimum is not None and maximum is not None
    assert minimum < maximum


def test_virtual_group_does_not_reuse_dali_group_record() -> None:
    addresses = {
        "Groups": [{"key": "0_g_0", "value": "Group 0"}],
        "Virtual Groups": [{"key": "0_v_0", "value": "Virtual Group 0"}],
    }
    devices = {
        "0_g_0": {
            "address": [0, "group", 0],
            "channel": 0,
            "dev_name": "Group 0",
            "hue_name": "All Dali",
            "dev_on": True,
            "level": 240,
            "device_ids": [1, 2],
        }
    }
    groups = reconcile_groups(addresses, devices, [])
    dali = next(group for group in groups if group.device_id == "0_g_0")
    virtual = next(group for group in groups if group.device_id == "0_v_0")
    assert dali.name == "All Dali"
    assert dali.is_on is True
    assert virtual.name == "Virtual Group 0"
    assert virtual.is_on is None
    assert virtual.members == ()


def test_group_without_color_temp_members_stays_brightness_only() -> None:
    addresses = {
        "Groups": [{"key": "0_g_1", "value": "Group 1"}],
        "Lights": [{"key": "0_s_11", "value": "Cabinet"}],
        "Virtual Groups": [],
    }
    devices = {
        "0_s_11": {
            "channel": 0,
            "short_addr": 11,
            "dev_name": "Cabinet",
            "dev_on": False,
            "groups": [1],
            "has_color_temp": False,
            "level": 0,
            "is_button": False,
            "is_io_device": False,
            "is_passive": False,
            "is_relay_device": False,
        },
        "0_g_1": {
            "address": [0, "group", 1],
            "channel": 0,
            "dev_name": "Group 1",
            "color_temp_k": 4000,
            "device_ids": [11],
        },
    }
    lights = reconcile_lights(addresses, devices)
    group = reconcile_groups(addresses, devices, lights)[0]
    assert group.has_color_temp is False
