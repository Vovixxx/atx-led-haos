from atx_led.brightness import dali_to_ha_brightness
from atx_led.const import MODE_CCT, MODE_DIMMER, MODE_RGB, MODE_RGB_CCT
from atx_led.models import (
    apply_derived_group_states,
    color_temp_range_kelvin,
    is_unsigned_driver,
    parse_device,
    reconcile_groups,
    reconcile_lights,
)
from atx_led.unsigned import (
    UnsignedOverrideError,
    apply_unsigned_overrides,
    merge_unsigned_override,
    normalize_unsigned_override,
    suggested_tune_values,
    unsigned_device_choices,
)


def test_empty_type_and_zero_serial_firmware_is_unsigned() -> None:
    raw = {
        "channel": 0,
        "short_addr": 16,
        "dev_name": "Kitchen Shade Cove",
        "serial_nb": 0,
        "fw_version": 0,
        "has_color_temp": False,
        "is_button": False,
        "is_io_device": False,
        "is_passive": False,
        "is_relay_device": False,
    }
    assert is_unsigned_driver(raw) is True
    device = parse_device("0_s_16", raw)
    assert device is not None
    assert device.unsigned is True
    assert device.unsigned_mode is None


def test_missing_type_serial_firmware_is_unsigned() -> None:
    raw = {"channel": 0, "short_addr": 11, "dev_name": "Cabinet"}
    assert is_unsigned_driver(raw) is True


def test_dev_type_present_is_known() -> None:
    raw = {
        "channel": 0,
        "short_addr": 1,
        "dev_type": 8,
        "serial_nb": 0,
        "fw_version": 0,
    }
    assert is_unsigned_driver(raw) is False


def test_nonzero_serial_is_known() -> None:
    raw = {"channel": 0, "short_addr": 1, "serial_nb": 2, "fw_version": 0}
    assert is_unsigned_driver(raw) is False


def test_nonzero_firmware_is_known() -> None:
    raw = {"channel": 0, "short_addr": 1, "serial_nb": 0, "fw_version": 12}
    assert is_unsigned_driver(raw) is False


def test_status_03_does_not_classify(
    addresses_payload: dict, devices_payload: dict
) -> None:
    lights = {light.device_id: light for light in reconcile_lights(addresses_payload, devices_payload)}
    hall = lights["0_s_1"]
    cabinet = lights["0_s_11"]
    cove = lights["0_s_16"]
    assert hall.unsigned is False
    assert hall.has_color_temp is True
    assert cabinet.unsigned is True
    assert cove.unsigned is True
    assert cabinet.status == 3


def test_normalize_rejects_inverted_dim_range() -> None:
    try:
        normalize_unsigned_override(
            {"mode": MODE_DIMMER, "min_level": 200, "max_level": 50}
        )
    except UnsignedOverrideError as err:
        assert err.code == "invalid_range"
    else:
        raise AssertionError("expected UnsignedOverrideError")


def test_normalize_requires_kelvin_for_cct() -> None:
    try:
        normalize_unsigned_override(
            {"mode": MODE_CCT, "min_level": 50, "max_level": 254}
        )
    except UnsignedOverrideError as err:
        assert err.code == "invalid_kelvin"
    else:
        raise AssertionError("expected UnsignedOverrideError")


def test_normalize_cct_keeps_typed_ends() -> None:
    assert normalize_unsigned_override(
        {
            "mode": MODE_CCT,
            "min_level": 50,
            "max_level": 254,
            "kelvin_min": 2700,
            "kelvin_max": 5000,
        }
    ) == {
        "mode": MODE_CCT,
        "min_level": 50,
        "max_level": 254,
        "kelvin_min": 2700,
        "kelvin_max": 5000,
    }


def test_override_min_maps_one_percent(
    addresses_payload: dict, devices_payload: dict
) -> None:
    lights = {light.device_id: light for light in reconcile_lights(addresses_payload, devices_payload)}
    updated = apply_unsigned_overrides(
        lights,
        {
            "0_s_16": {
                "mode": MODE_DIMMER,
                "min_level": 50,
                "max_level": 254,
            }
        },
    )
    cove = updated["0_s_16"]
    assert cove.min_level == 50
    assert cove.max_level == 254
    assert cove.has_color_temp is False
    assert dali_to_ha_brightness(cove.min_level, cove.min_level, cove.max_level) == 1


def test_cct_override_sets_slider_ends(
    addresses_payload: dict, devices_payload: dict
) -> None:
    lights = {light.device_id: light for light in reconcile_lights(addresses_payload, devices_payload)}
    updated = apply_unsigned_overrides(
        lights,
        {
            "0_s_16": {
                "mode": MODE_CCT,
                "min_level": 50,
                "max_level": 254,
                "kelvin_min": 2700,
                "kelvin_max": 5000,
            }
        },
    )
    cove = updated["0_s_16"]
    assert cove.has_color_temp is True
    assert cove.has_color_rgb is False
    assert cove.unsigned_mode == MODE_CCT
    minimum, maximum = color_temp_range_kelvin(cove.user_warm, cove.user_cool)
    assert minimum is not None and maximum is not None
    assert minimum < maximum
    assert abs(minimum - 2700) <= 5
    assert abs(maximum - 5000) <= 5


def test_known_fixture_override_is_ignored(
    addresses_payload: dict, devices_payload: dict
) -> None:
    lights = {light.device_id: light for light in reconcile_lights(addresses_payload, devices_payload)}
    hall_before = lights["0_s_1"]
    updated = apply_unsigned_overrides(
        lights,
        {
            "0_s_1": {
                "mode": MODE_DIMMER,
                "min_level": 1,
                "max_level": 10,
            }
        },
    )
    assert updated["0_s_1"] is hall_before
    assert updated["0_s_1"].min_level == 50
    assert updated["0_s_1"].has_color_temp is True


def test_rgb_mode_sets_flag_but_not_cct(
    addresses_payload: dict, devices_payload: dict
) -> None:
    lights = {light.device_id: light for light in reconcile_lights(addresses_payload, devices_payload)}
    updated = apply_unsigned_overrides(
        lights,
        {"0_s_11": {"mode": MODE_RGB, "min_level": 1, "max_level": 254}},
    )
    cabinet = updated["0_s_11"]
    assert cabinet.has_color_rgb is True
    assert cabinet.has_color_temp is False
    assert cabinet.unsigned_mode == MODE_RGB


def test_group_gains_cct_after_unsigned_member_override() -> None:
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
            "serial_nb": 0,
            "fw_version": 0,
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
            "device_ids": [11],
        },
    }
    lights = {light.device_id: light for light in reconcile_lights(addresses, devices)}
    groups = {
        group.device_id: group
        for group in reconcile_groups(addresses, devices, list(lights.values()))
    }
    assert groups["0_g_1"].has_color_temp is False
    lights = apply_unsigned_overrides(
        lights,
        {
            "0_s_11": {
                "mode": MODE_CCT,
                "min_level": 50,
                "max_level": 254,
                "kelvin_min": 2700,
                "kelvin_max": 5000,
            }
        },
    )
    groups = apply_derived_group_states(groups, lights)
    assert groups["0_g_1"].has_color_temp is True


def test_choices_list_only_unsigned(
    addresses_payload: dict, devices_payload: dict
) -> None:
    lights = {light.device_id: light for light in reconcile_lights(addresses_payload, devices_payload)}
    choices = unsigned_device_choices(lights)
    assert "0_s_11" in choices
    assert "0_s_16" in choices
    assert "0_s_1" not in choices
    assert choices["0_s_16"] == "Cove Light (0_s_16)"


def test_merge_override_preserves_other_devices() -> None:
    options = merge_unsigned_override(
        {"unsigned_overrides": {"0_s_11": {"mode": MODE_DIMMER, "min_level": 1, "max_level": 254}}},
        "0_s_16",
        {"mode": MODE_CCT, "min_level": 50, "max_level": 254, "kelvin_min": 2700, "kelvin_max": 5000},
    )
    assert set(options["unsigned_overrides"]) == {"0_s_11", "0_s_16"}
