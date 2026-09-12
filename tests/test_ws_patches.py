import json

from atx_led.models import apply_device_patches, parse_ws_patches, reconcile_lights


def test_parse_ws_patches_reads_device_payload() -> None:
    payload = [
        {
            "addr": "0_s_1",
            "data": {
                "channel": 0,
                "short_addr": 1,
                "dev_on": True,
                "level": 86,
                "address": [0, "single", 1],
                "dev_name": "Hall Light",
                "fail_level": 86,
                "power_on_level": 86,
            },
        }
    ]
    patches = parse_ws_patches(json.dumps(payload))
    assert patches == [
        (
            "0_s_1",
            {
                "channel": 0,
                "short_addr": 1,
                "dev_on": True,
                "level": 86,
                "address": [0, "single", 1],
                "dev_name": "Hall Light",
                "fail_level": 86,
                "power_on_level": 86,
            },
        )
    ]


def test_parse_ws_patches_ignores_malformed_payloads() -> None:
    assert parse_ws_patches("not-json") == []
    assert parse_ws_patches({"addr": "0_s_1"}) == []
    assert parse_ws_patches([{"addr": "0_s_1"}]) == []
    assert parse_ws_patches([{"data": {"dev_on": True}}]) == []


def test_patch_turns_off_without_losing_capabilities_or_level(
    addresses_payload: dict, devices_payload: dict
) -> None:
    lights = {light.device_id: light for light in reconcile_lights(addresses_payload, devices_payload)}
    updated = apply_device_patches(
        lights,
        [
            (
                "0_s_1",
                {
                    "dev_on": False,
                    "level": 86,
                    "fail_level": 0,
                    "power_on_level": 0,
                },
            )
        ],
    )
    hall = updated["0_s_1"]
    assert hall.is_on is False
    assert hall.stored_level == 86
    assert hall.has_color_temp is True
    assert hall.min_level == 50
    assert hall.max_level == 250
    assert hall.color_temp_k == 4065


def test_patch_does_not_create_unknown_or_ineligible_devices(
    addresses_payload: dict, devices_payload: dict
) -> None:
    lights = {light.device_id: light for light in reconcile_lights(addresses_payload, devices_payload)}
    original_ids = set(lights)
    updated = apply_device_patches(
        lights,
        [
            ("0_s_99", {"dev_on": True, "level": 10}),
            ("0_g_0", {"dev_on": True, "level": 46}),
        ],
    )
    assert set(updated) == original_ids
    assert "0_s_99" not in updated


def test_unrelated_lights_are_unchanged(
    addresses_payload: dict, devices_payload: dict
) -> None:
    lights = {light.device_id: light for light in reconcile_lights(addresses_payload, devices_payload)}
    cabinet_before = lights["0_s_11"]
    updated = apply_device_patches(lights, [("0_s_1", {"dev_on": True, "level": 86})])
    assert updated["0_s_1"].is_on is True
    assert updated["0_s_11"] is cabinet_before
