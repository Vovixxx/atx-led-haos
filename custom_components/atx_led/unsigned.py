"""Home Assistant-only overrides for unsigned leftover drivers."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .const import (
    CONF_UNSIGNED_OVERRIDES,
    DEFAULT_KELVIN_MAX,
    DEFAULT_KELVIN_MIN,
    MODE_CCT,
    MODE_DIMMER,
    MODE_RGB,
    MODE_RGB_CCT,
    UNSIGNED_MODES,
)
from .models import LightDevice, color_temp_range_kelvin
from .protocol import DALI_MAX_ARC_LEVEL

_CCT_MODES = {MODE_CCT, MODE_RGB_CCT}
_RGB_MODES = {MODE_RGB, MODE_RGB_CCT}


class UnsignedOverrideError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def kelvin_to_mired(kelvin: int) -> int | None:
    if kelvin <= 0:
        return None
    return round(1_000_000 / kelvin)


def normalize_unsigned_override(user_input: dict[str, Any]) -> dict[str, Any]:
    mode = str(user_input.get("mode") or "")
    if mode not in UNSIGNED_MODES:
        raise UnsignedOverrideError("invalid_range")
    try:
        min_level = int(user_input["min_level"])
        max_level = int(user_input["max_level"])
    except (KeyError, TypeError, ValueError) as err:
        raise UnsignedOverrideError("invalid_range") from err
    if not 1 <= min_level <= DALI_MAX_ARC_LEVEL or not 1 <= max_level <= DALI_MAX_ARC_LEVEL:
        raise UnsignedOverrideError("invalid_range")
    if min_level >= max_level:
        raise UnsignedOverrideError("invalid_range")
    result: dict[str, Any] = {
        "mode": mode,
        "min_level": min_level,
        "max_level": max_level,
    }
    if mode in _CCT_MODES:
        try:
            kelvin_min = int(user_input["kelvin_min"])
            kelvin_max = int(user_input["kelvin_max"])
        except (KeyError, TypeError, ValueError) as err:
            raise UnsignedOverrideError("invalid_kelvin") from err
        if kelvin_min < 1000 or kelvin_max > 20000 or kelvin_min >= kelvin_max:
            raise UnsignedOverrideError("invalid_kelvin")
        result["kelvin_min"] = kelvin_min
        result["kelvin_max"] = kelvin_max
    return result


def apply_unsigned_override(device: LightDevice, override: dict) -> LightDevice:
    try:
        normalized = normalize_unsigned_override(override)
    except UnsignedOverrideError:
        return device
    mode = normalized["mode"]
    updates: dict[str, Any] = {
        "min_level": normalized["min_level"],
        "max_level": normalized["max_level"],
        "unsigned_mode": mode,
        "has_color_temp": mode in _CCT_MODES,
        "has_color_rgb": mode in _RGB_MODES,
    }
    if mode in _CCT_MODES:
        warm = kelvin_to_mired(normalized["kelvin_min"])
        cool = kelvin_to_mired(normalized["kelvin_max"])
        if warm is None or cool is None:
            return device
        updates["user_warm"] = max(warm, cool)
        updates["user_cool"] = min(warm, cool)
    else:
        updates["user_warm"] = None
        updates["user_cool"] = None
    return replace(device, **updates)


def apply_unsigned_overrides(
    lights: dict[str, LightDevice], overrides: object
) -> dict[str, LightDevice]:
    if not isinstance(overrides, dict) or not overrides:
        return lights
    updated = dict(lights)
    changed = False
    for device_id, override in overrides.items():
        device = updated.get(str(device_id))
        if device is None or not device.unsigned or not isinstance(override, dict):
            continue
        merged = apply_unsigned_override(device, override)
        if merged is not device:
            updated[str(device_id)] = merged
            changed = True
    return updated if changed else lights


def unsigned_device_choices(lights: dict[str, LightDevice]) -> dict[str, str]:
    return {
        device_id: f"{light.name} ({device_id})"
        for device_id, light in lights.items()
        if light.unsigned
    }


def suggested_tune_values(
    light: LightDevice, override: dict | None
) -> dict[str, object]:
    source = override if isinstance(override, dict) else {}
    values: dict[str, object] = {
        "mode": source.get("mode") or light.unsigned_mode or MODE_DIMMER,
        "min_level": source.get("min_level", light.min_level),
        "max_level": source.get("max_level", light.max_level),
        "kelvin_min": source.get("kelvin_min", DEFAULT_KELVIN_MIN),
        "kelvin_max": source.get("kelvin_max", DEFAULT_KELVIN_MAX),
    }
    if not source and light.has_color_temp:
        minimum, maximum = color_temp_range_kelvin(light.user_warm, light.user_cool)
        if minimum and maximum:
            values["kelvin_min"] = minimum
            values["kelvin_max"] = maximum
    return values


def unsigned_diagnostics(light: LightDevice) -> dict[str, object]:
    payload: dict[str, object] = {"unsigned": light.unsigned}
    if not light.unsigned_mode:
        return payload
    payload["unsigned_mode"] = light.unsigned_mode
    payload["min_level"] = light.min_level
    payload["max_level"] = light.max_level
    if light.has_color_temp:
        minimum, maximum = color_temp_range_kelvin(light.user_warm, light.user_cool)
        if minimum and maximum:
            payload["kelvin_min"] = minimum
            payload["kelvin_max"] = maximum
    return payload


def merge_unsigned_override(
    options: dict, device_id: str, override: dict
) -> dict:
    merged = dict(options)
    overrides = dict(merged.get(CONF_UNSIGNED_OVERRIDES) or {})
    overrides[device_id] = override
    merged[CONF_UNSIGNED_OVERRIDES] = overrides
    return merged
