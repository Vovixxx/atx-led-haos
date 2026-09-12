from atx_led.brightness import dali_to_ha_brightness, ha_brightness_to_dali, normalize_level_range


def test_verified_raw_185_is_locked_hub_ui_68_percent() -> None:
    ha = dali_to_ha_brightness(185, min_level=50, max_level=250)
    assert ha is not None
    percent = (185 - 50) / (250 - 50) * 100
    assert percent == 67.5
    assert abs(ha / 255 * 100 - percent) < 0.5
    assert round(percent) == 68


def test_raw_185_round_trips_through_ha_brightness() -> None:
    ha = dali_to_ha_brightness(185, min_level=50, max_level=250)
    assert ha is not None
    assert ha_brightness_to_dali(ha, min_level=50, max_level=250) == 185


def test_zero_is_off_not_minimum() -> None:
    assert ha_brightness_to_dali(0, min_level=50, max_level=250) == 0
    assert dali_to_ha_brightness(0, min_level=50, max_level=250) is None


def test_full_ha_brightness_uses_device_max_not_254() -> None:
    assert ha_brightness_to_dali(255, min_level=50, max_level=250) == 250


def test_never_emits_dali_mask() -> None:
    assert ha_brightness_to_dali(255, min_level=1, max_level=254) == 254
    assert ha_brightness_to_dali(255, min_level=1, max_level=255) == 254


def test_equal_min_max_uses_that_level_when_on() -> None:
    assert normalize_level_range(100, 100) == (100, 100)
    assert ha_brightness_to_dali(128, min_level=100, max_level=100) == 100
    assert dali_to_ha_brightness(100, min_level=100, max_level=100) == 255


def test_invalid_inverted_range_swaps_to_usable_bounds() -> None:
    assert normalize_level_range(200, 50) == (50, 200)
