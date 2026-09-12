"""Map Home Assistant brightness to hub-style DALI levels."""

from __future__ import annotations

from .protocol import DALI_MAX_ARC_LEVEL


def normalize_level_range(min_level: int, max_level: int) -> tuple[int, int]:
    """Return a usable min/max, never emitting MASK as a target level."""
    minimum = max(0, int(min_level))
    maximum = max(0, int(max_level))
    if minimum > maximum:
        minimum, maximum = maximum, minimum
    maximum = min(maximum, DALI_MAX_ARC_LEVEL)
    if minimum > DALI_MAX_ARC_LEVEL:
        minimum = DALI_MAX_ARC_LEVEL
    if maximum < 1 and minimum < 1:
        return (1, DALI_MAX_ARC_LEVEL)
    if maximum < 1:
        maximum = DALI_MAX_ARC_LEVEL
    return (minimum, maximum)


def ha_brightness_to_dali(ha_brightness: int, min_level: int, max_level: int) -> int:
    """Convert HA 0-255 brightness to a DALI arc level.

    0 is off. Non-zero values use the locked hub UI mapping
    ``percent = (raw - min) / (max - min)``. This matched the address-1
    185 → 68% observation and was confirmed in Home Assistant.
    """
    if ha_brightness <= 0:
        return 0
    minimum, maximum = normalize_level_range(min_level, max_level)
    if minimum == maximum:
        return minimum
    ratio = min(int(ha_brightness), 255) / 255
    raw = round(minimum + ratio * (maximum - minimum))
    return max(minimum, min(maximum, raw))


def dali_to_ha_brightness(raw_level: int, min_level: int, max_level: int) -> int | None:
    """Convert a DALI arc level to HA 1-255 brightness. 0 / missing is None."""
    if raw_level is None or raw_level <= 0:
        return None
    minimum, maximum = normalize_level_range(min_level, max_level)
    if minimum == maximum:
        return 255
    ratio = (raw_level - minimum) / (maximum - minimum)
    ha = round(ratio * 255)
    return max(1, min(255, ha))


def use_hub_device_level_for_brightness(is_on: bool | None) -> bool:
    """Dim while already on uses the hub device POST so fade can apply."""
    return is_on is True
