from atx_led.models import (
    color_temp_range_kelvin,
    hub_unique_id,
    normalize_host,
    reconcile_lights,
)


def test_normalize_host_strips_scheme_and_path() -> None:
    assert normalize_host("http://192.168.1.50/dali/devices") == "192.168.1.50"
    assert normalize_host(" 192.168.1.50 ") == "192.168.1.50"


def test_hub_unique_id_uses_normalized_host_fallback() -> None:
    assert hub_unique_id("http://192.168.1.50") == "atx_led_192.168.1.50"


def test_reconcile_creates_only_commissioned_lights(
    addresses_payload: dict, devices_payload: dict
) -> None:
    lights = reconcile_lights(addresses_payload, devices_payload)
    ids = [light.device_id for light in lights]
    assert ids == ["0_s_1", "0_s_11", "0_s_21", "0_s_16"]
    assert all(not light.is_button for light in lights)


def test_hue_hidden_does_not_exclude_lights(
    addresses_payload: dict, devices_payload: dict
) -> None:
    lights = reconcile_lights(addresses_payload, devices_payload)
    hall = next(light for light in lights if light.device_id == "0_s_1")
    assert hall.hue_hidden is True
    assert hall.name == "Hall Light"


def test_off_light_keeps_stored_level_but_is_not_on(
    addresses_payload: dict, devices_payload: dict
) -> None:
    lights = reconcile_lights(addresses_payload, devices_payload)
    hall = next(light for light in lights if light.device_id == "0_s_1")
    assert hall.is_on is False
    assert hall.stored_level == 185


def test_capabilities_come_from_flags_not_populated_color_fields(
    addresses_payload: dict, devices_payload: dict
) -> None:
    lights = reconcile_lights(addresses_payload, devices_payload)
    cabinet = next(light for light in lights if light.device_id == "0_s_11")
    hall = next(light for light in lights if light.device_id == "0_s_1")
    assert cabinet.has_color_temp is False
    assert cabinet.color_temp_k == 2702
    assert hall.has_color_temp is True


def test_names_are_stripped(
    addresses_payload: dict, devices_payload: dict
) -> None:
    lights = reconcile_lights(addresses_payload, devices_payload)
    cove = next(light for light in lights if light.device_id == "0_s_16")
    assert cove.name == "Cove Light"


def test_missing_device_record_is_skipped_not_fatal(addresses_payload: dict) -> None:
    lights = reconcile_lights(addresses_payload, {"0_s_1": {
        "channel": 0,
        "short_addr": 1,
        "dev_name": "Hall Light",
        "dev_on": False,
        "has_color_temp": True,
        "is_button": False,
        "is_io_device": False,
        "is_passive": False,
        "is_relay_device": False,
        "level": 185,
        "min_level": 50,
        "max_level": 250,
    }})
    assert [light.device_id for light in lights] == ["0_s_1"]


def test_color_range_uses_user_mireds_not_cct_defaults() -> None:
    minimum, maximum = color_temp_range_kelvin(user_warm=370, user_cool=200)
    assert minimum == 2703
    assert maximum == 5000


def test_stored_temp_outside_user_range_is_preserved(
    addresses_payload: dict, devices_payload: dict
) -> None:
    lights = reconcile_lights(addresses_payload, devices_payload)
    office = next(light for light in lights if light.device_id == "0_s_21")
    assert office.color_temp_k == 2702
    minimum, maximum = color_temp_range_kelvin(office.user_warm, office.user_cool)
    assert office.color_temp_k < minimum
    assert maximum == 6494
