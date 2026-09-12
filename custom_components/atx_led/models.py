"""Normalized hub inventory for the ATX LED integration."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class LightDevice:
    device_id: str
    channel: int
    short_addr: int
    name: str
    is_on: bool | None
    stored_level: int | None
    min_level: int
    max_level: int
    has_color_temp: bool
    has_color_rgb: bool
    color_temp_k: int | None
    user_warm: int | None
    user_cool: int | None
    status: int | None
    hue_hidden: bool
    is_button: bool
    is_io_device: bool
    is_passive: bool
    is_relay_device: bool
    available: bool = True

    @property
    def unique_suffix(self) -> str:
        return f"{self.channel}_{self.short_addr}"


def normalize_host(host: str) -> str:
    value = host.strip()
    if "://" in value:
        parsed = urlparse(value)
        if parsed.netloc:
            return parsed.netloc
        value = value.split("://", 1)[1]
    return value.split("/", 1)[0].strip()


def hub_unique_id(host: str) -> str:
    """Fallback hub identity until a stable hardware identifier is verified."""
    return f"atx_led_{normalize_host(host)}"


def _as_bool(value: object) -> bool:
    return bool(value)


def _as_optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: object, default: int) -> int:
    parsed = _as_optional_int(value)
    return default if parsed is None else parsed


def parse_device(device_id: str, raw: dict) -> LightDevice | None:
    if not isinstance(raw, dict):
        return None
    short_addr = _as_optional_int(raw.get("short_addr"))
    if short_addr is None:
        address = raw.get("address")
        if isinstance(address, list) and len(address) >= 3:
            short_addr = _as_optional_int(address[2])
    if short_addr is None:
        return None
    name = str(raw.get("dev_name") or device_id).strip()
    is_on_raw = raw.get("dev_on")
    is_on = None if is_on_raw is None else bool(is_on_raw)
    return LightDevice(
        device_id=device_id,
        channel=_as_int(raw.get("channel"), 0),
        short_addr=short_addr,
        name=name,
        is_on=is_on,
        stored_level=_as_optional_int(raw.get("level")),
        min_level=_as_int(raw.get("min_level"), 1),
        max_level=_as_int(raw.get("max_level"), 254),
        has_color_temp=_as_bool(raw.get("has_color_temp")),
        has_color_rgb=_as_bool(raw.get("has_color_rgb")),
        color_temp_k=_as_optional_int(raw.get("color_temp_k")),
        user_warm=_as_optional_int(raw.get("user_warm")),
        user_cool=_as_optional_int(raw.get("user_cool")),
        status=_as_optional_int(raw.get("dev_status")),
        hue_hidden=_as_bool(raw.get("hue_hidden")),
        is_button=_as_bool(raw.get("is_button")),
        is_io_device=_as_bool(raw.get("is_io_device")),
        is_passive=_as_bool(raw.get("is_passive")),
        is_relay_device=_as_bool(raw.get("is_relay_device")),
    )


def _is_eligible_light(device: LightDevice) -> bool:
    if device.is_button or device.is_io_device or device.is_passive:
        return False
    if device.is_relay_device:
        return False
    return True


def reconcile_lights(addresses: dict, devices: dict) -> list[LightDevice]:
    """Join known light addresses with device records. Partial misses are skipped."""
    lights_list = []
    if isinstance(addresses, dict):
        lights_list = addresses.get("Lights") or []
    light_ids: list[str] = []
    for item in lights_list:
        if isinstance(item, dict) and item.get("key"):
            light_ids.append(str(item["key"]))
        elif isinstance(item, str):
            light_ids.append(item)

    if not isinstance(devices, dict):
        return []

    result: list[LightDevice] = []
    for device_id in light_ids:
        raw = devices.get(device_id)
        if not isinstance(raw, dict):
            continue
        device = parse_device(device_id, raw)
        if device is None or not _is_eligible_light(device):
            continue
        result.append(device)
    return result


def mired_to_kelvin(mired: int) -> int | None:
    if mired <= 0:
        return None
    return round(1_000_000 / mired)


def color_temp_range_kelvin(
    user_warm: int | None, user_cool: int | None
) -> tuple[int, int] | tuple[None, None]:
    """Convert hub user_warm/user_cool mired-like values to a Kelvin slider range."""
    if not user_warm or not user_cool:
        return (None, None)
    warm_k = mired_to_kelvin(user_warm)
    cool_k = mired_to_kelvin(user_cool)
    if warm_k is None or cool_k is None or warm_k == cool_k:
        return (None, None)
    return (min(warm_k, cool_k), max(warm_k, cool_k))
