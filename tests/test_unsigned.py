from atx_led.models import is_unsigned_driver, parse_device, reconcile_lights


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
