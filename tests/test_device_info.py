from atx_led.device_info import light_device_registry_info


def test_light_device_info_uses_via_device_id_not_identifier_tuple() -> None:
    info = light_device_registry_info(
        unique_id="atx_led_192.168.1.50_0_1",
        name="Hall Light",
        hub_device_id="hub-registry-id",
    )
    assert info["via_device_id"] == "hub-registry-id"
    assert "via_device" not in info
    assert info["identifiers"] == {("atx_led", "atx_led_192.168.1.50_0_1")}
    assert info["name"] == "Hall Light"


def test_missing_hub_device_id_does_not_emit_deprecated_via_device() -> None:
    info = light_device_registry_info(unique_id="light-1", name="Hall Light")
    assert "via_device" not in info
    assert "via_device_id" not in info
