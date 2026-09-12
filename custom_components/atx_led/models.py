"""Normalized hub inventory for the ATX LED integration."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
import re
from urllib.parse import urlparse

from .protocol import GROUP_ADDR_MAX, SCENE_MAX, SHORT_ADDR_MAX


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
    group_membership: tuple[int, ...] = ()
    available: bool = True

    @property
    def unique_suffix(self) -> str:
        return f"{self.channel}_{self.short_addr}"


GROUP_KIND_DALI = "dali"
GROUP_KIND_VIRTUAL = "virtual"

_ADDR_ID_RE = re.compile(r"^(\d+)_([sgv])_(\d+)$")
_SCENE_ID_RE = re.compile(r"^(\d+)_(?:sc|scene|n)_(\d+)$")


@dataclass(frozen=True)
class GroupDevice:
    """A commissioned DALI group or hub virtual group."""

    device_id: str
    channel: int
    group_addr: int
    kind: str
    name: str
    is_on: bool | None
    stored_level: int | None
    min_level: int
    max_level: int
    has_color_temp: bool
    color_temp_k: int | None
    user_warm: int | None
    user_cool: int | None
    members: tuple[str, ...]
    available: bool = True

    @property
    def unique_suffix(self) -> str:
        prefix = "g" if self.kind == GROUP_KIND_DALI else "v"
        return f"{prefix}_{self.channel}_{self.group_addr}"

    @property
    def is_dali_group(self) -> bool:
        return self.kind == GROUP_KIND_DALI


@dataclass(frozen=True)
class SceneDevice:
    """A named hub scene that can recall DALI scene levels."""

    scene_id: str
    name: str
    channel: int | None
    dali_scene: int | None
    group_addr: int | None
    members: tuple[str, ...]

    @property
    def unique_suffix(self) -> str:
        return f"scene_{self.scene_id}"


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
        group_membership=_parse_group_membership(raw.get("groups")),
    )


def parse_addr_id(device_id: str) -> tuple[int, str, int] | None:
    """Parse hub IDs such as ``0_s_1``, ``0_g_1``, and ``0_v_0``."""
    match = _ADDR_ID_RE.match(str(device_id).strip())
    if match is None:
        return None
    return (int(match.group(1)), match.group(2), int(match.group(3)))


def _parse_group_membership(value: object) -> tuple[int, ...]:
    if isinstance(value, list):
        groups: list[int] = []
        for item in value:
            parsed = _as_optional_int(item)
            if parsed is None or parsed < 0 or parsed > GROUP_ADDR_MAX:
                continue
            if parsed not in groups:
                groups.append(parsed)
        return tuple(groups)
    bitmask = _as_optional_int(value)
    if bitmask is None or bitmask <= 0:
        return ()
    return tuple(index for index in range(GROUP_ADDR_MAX + 1) if bitmask & (1 << index))


def _address_keys(addresses: dict, category: str) -> list[tuple[str, str]]:
    items = addresses.get(category) or [] if isinstance(addresses, dict) else []
    result: list[tuple[str, str]] = []
    for item in items:
        if isinstance(item, dict) and item.get("key"):
            key = str(item["key"])
            name = str(item.get("value") or key).strip() or key
            result.append((key, name))
        elif isinstance(item, str) and item:
            result.append((item, item))
    return result


def _member_ids(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        members: list[str] = []
        for item in value:
            if isinstance(item, str) and item and item not in members:
                members.append(item)
            elif isinstance(item, dict) and item.get("key"):
                key = str(item["key"])
                if key and key not in members:
                    members.append(key)
        return tuple(members)
    if isinstance(value, str) and value:
        return (value,)
    return ()


def parse_group(
    device_id: str,
    raw: dict | None,
    *,
    name_fallback: str,
    kind: str,
) -> GroupDevice | None:
    parsed = parse_addr_id(device_id)
    channel = 0
    group_addr: int | None = None
    if parsed is not None:
        channel, marker, group_addr = parsed
        if marker == "g":
            kind = GROUP_KIND_DALI
        elif marker == "v":
            kind = GROUP_KIND_VIRTUAL
        elif marker == "s":
            return None
    if isinstance(raw, dict):
        channel = _as_int(raw.get("channel"), channel)
        address = raw.get("address")
        if isinstance(address, list) and len(address) >= 3:
            group_addr = _as_optional_int(address[2]) if group_addr is None else group_addr
        if group_addr is None:
            group_addr = _as_optional_int(raw.get("short_addr") or raw.get("group_addr"))
        name = str(raw.get("dev_name") or name_fallback or device_id).strip()
        is_on_raw = raw.get("dev_on")
        is_on = None if is_on_raw is None else bool(is_on_raw)
        members = (
            _member_ids(raw.get("members"))
            or _member_ids(raw.get("lights"))
            or _member_ids(raw.get("devices"))
        )
        return GroupDevice(
            device_id=device_id,
            channel=channel,
            group_addr=group_addr if group_addr is not None else 0,
            kind=kind,
            name=name,
            is_on=is_on,
            stored_level=_as_optional_int(raw.get("level")),
            min_level=_as_int(raw.get("min_level"), 1),
            max_level=_as_int(raw.get("max_level"), 254),
            has_color_temp=_as_bool(raw.get("has_color_temp")),
            color_temp_k=_as_optional_int(raw.get("color_temp_k")),
            user_warm=_as_optional_int(raw.get("user_warm")),
            user_cool=_as_optional_int(raw.get("user_cool")),
            members=members,
        )
    if group_addr is None:
        return None
    return GroupDevice(
        device_id=device_id,
        channel=channel,
        group_addr=group_addr,
        kind=kind,
        name=str(name_fallback or device_id).strip(),
        is_on=None,
        stored_level=None,
        min_level=1,
        max_level=254,
        has_color_temp=False,
        color_temp_k=None,
        user_warm=None,
        user_cool=None,
        members=(),
    )


def _infer_group_members(
    groups: list[GroupDevice], lights: list[LightDevice]
) -> list[GroupDevice]:
    """Fill empty DALI group member lists from fixture group membership."""
    if not groups:
        return groups
    by_group: dict[tuple[int, int], list[str]] = {}
    for light in lights:
        for group_addr in light.group_membership:
            by_group.setdefault((light.channel, group_addr), []).append(light.device_id)
    updated: list[GroupDevice] = []
    changed = False
    for group in groups:
        if group.members or not group.is_dali_group:
            updated.append(group)
            continue
        inferred = tuple(by_group.get((group.channel, group.group_addr), ()))
        if inferred:
            updated.append(replace(group, members=inferred))
            changed = True
        else:
            updated.append(group)
    return updated if changed else groups


def reconcile_groups(
    addresses: dict, devices: dict, lights: list[LightDevice] | None = None
) -> list[GroupDevice]:
    """Join known group addresses with device records. Skip broadcast ``all``."""
    if not isinstance(devices, dict):
        devices = {}
    result: list[GroupDevice] = []
    seen: set[str] = set()
    for category, kind in (
        ("Groups", GROUP_KIND_DALI),
        ("Virtual Groups", GROUP_KIND_VIRTUAL),
    ):
        for device_id, name in _address_keys(addresses if isinstance(addresses, dict) else {}, category):
            if device_id in seen or device_id == "all":
                continue
            raw = devices.get(device_id)
            group = parse_group(
                device_id,
                raw if isinstance(raw, dict) else None,
                name_fallback=name,
                kind=kind,
            )
            if group is None:
                continue
            seen.add(device_id)
            result.append(group)
    if lights:
        result = _infer_group_members(result, lights)
    return result


def _parse_scene_id(scene_id: str) -> tuple[int | None, int | None]:
    match = _SCENE_ID_RE.match(str(scene_id).strip())
    if match is not None:
        return (int(match.group(1)), int(match.group(2)))
    trailing = re.search(r"(\d+)$", str(scene_id).strip())
    if trailing is None:
        return (None, None)
    scene = int(trailing.group(1))
    return (None, scene if 0 <= scene <= SCENE_MAX else None)


def parse_scene(scene_id: str, raw: dict | None, name_fallback: str | None = None) -> SceneDevice | None:
    """Normalize one hub scene record. Missing DALI numbers are kept as None."""
    channel, dali_scene = _parse_scene_id(scene_id)
    group_addr: int | None = None
    members: tuple[str, ...] = ()
    name = str(name_fallback or scene_id).strip() or scene_id
    if isinstance(raw, dict):
        name = str(raw.get("dev_name") or raw.get("name") or raw.get("value") or name).strip()
        channel = _as_optional_int(raw.get("channel")) if raw.get("channel") is not None else channel
        for key in ("scene", "scene_number", "dali_scene", "number"):
            if key in raw:
                parsed_scene = _as_optional_int(raw.get(key))
                if parsed_scene is not None:
                    dali_scene = parsed_scene
                    break
        for key in ("group", "group_addr"):
            if key in raw:
                parsed_group = _as_optional_int(raw.get(key))
                if parsed_group is not None:
                    group_addr = parsed_group
                    break
        members = (
            _member_ids(raw.get("members"))
            or _member_ids(raw.get("lights"))
            or _member_ids(raw.get("devices"))
        )
    if dali_scene is not None and not 0 <= dali_scene <= SCENE_MAX:
        dali_scene = None
    if group_addr is not None and not 0 <= group_addr <= GROUP_ADDR_MAX:
        group_addr = None
    return SceneDevice(
        scene_id=str(scene_id),
        name=name,
        channel=channel,
        dali_scene=dali_scene,
        group_addr=group_addr,
        members=members,
    )


def parse_scenes(payload: object) -> list[SceneDevice]:
    """Decode GET /dali/api/scenes in the shapes observed from hub-style APIs."""
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode()
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return []
    if isinstance(payload, dict) and ("Scenes" in payload or "scenes" in payload):
        nested = payload.get("Scenes")
        if nested is None:
            nested = payload.get("scenes")
        payload = nested
    items: list[tuple[str, dict | None, str | None]] = []
    if isinstance(payload, dict):
        for scene_id, raw in payload.items():
            if str(scene_id) in {"Scenes", "scenes", "ok"}:
                continue
            if isinstance(raw, dict):
                name = raw.get("name") or raw.get("value") or raw.get("dev_name")
                items.append((str(scene_id), raw, str(name) if name else None))
            elif isinstance(raw, str) and raw:
                items.append((str(scene_id), None, raw))
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            if isinstance(item, dict) and item.get("key"):
                items.append((str(item["key"]), item, str(item.get("value") or item["key"])))
            elif isinstance(item, dict) and item.get("id"):
                items.append((str(item["id"]), item, str(item.get("name") or item["id"])))
            elif isinstance(item, str) and item:
                items.append((item, None, item))
            elif isinstance(item, dict):
                items.append((str(item.get("dev_name") or item.get("name") or index), item, None))
    scenes: list[SceneDevice] = []
    seen: set[str] = set()
    for scene_id, raw, name_fallback in items:
        if scene_id in seen:
            continue
        scene = parse_scene(scene_id, raw, name_fallback)
        if scene is None:
            continue
        seen.add(scene_id)
        scenes.append(scene)
    return scenes


def scene_short_addrs(members: tuple[str, ...], lights: dict[str, LightDevice]) -> list[int]:
    """Resolve scene members to DALI short addresses, skipping ineligible IDs."""
    addrs: list[int] = []
    for member_id in members:
        light = lights.get(member_id)
        if light is not None:
            if 0 <= light.short_addr <= SHORT_ADDR_MAX and light.short_addr not in addrs:
                addrs.append(light.short_addr)
            continue
        parsed = parse_addr_id(member_id)
        if parsed is None or parsed[1] != "s":
            continue
        short_addr = parsed[2]
        if 0 <= short_addr <= SHORT_ADDR_MAX and short_addr not in addrs:
            addrs.append(short_addr)
    return addrs


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


def parse_ws_patches(payload: object) -> list[tuple[str, dict]]:
    """Decode a verified `/ws/dali/devices` JSON array into (addr, data) patches."""
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode()
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return []
    if not isinstance(payload, list):
        return []
    patches: list[tuple[str, dict]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        addr = item.get("addr")
        data = item.get("data")
        if isinstance(addr, str) and addr and isinstance(data, dict):
            patches.append((addr, data))
    return patches


def apply_device_patch(device: LightDevice, data: dict) -> LightDevice:
    """Merge a partial hub patch without dropping capabilities or dimming limits."""
    updates: dict[str, object] = {}
    if "dev_on" in data:
        updates["is_on"] = bool(data["dev_on"])
    if "level" in data:
        updates["stored_level"] = _as_optional_int(data["level"])
    if "dev_name" in data and data["dev_name"] not in (None, ""):
        updates["name"] = str(data["dev_name"]).strip()
    if "color_temp_k" in data:
        updates["color_temp_k"] = _as_optional_int(data["color_temp_k"])
    if "dev_status" in data:
        updates["status"] = _as_optional_int(data["dev_status"])
    if not updates:
        return device
    return replace(device, **updates)


def apply_device_patches(
    lights: dict[str, LightDevice], patches: list[tuple[str, dict]]
) -> dict[str, LightDevice]:
    """Apply patches to known lights only. Unknown addrs are ignored."""
    if not patches:
        return lights
    updated = dict(lights)
    changed = False
    for addr, data in patches:
        current = updated.get(addr)
        if current is None:
            continue
        merged = apply_device_patch(current, data)
        if merged is not current:
            updated[addr] = merged
            changed = True
    return updated if changed else lights


def apply_group_patch(group: GroupDevice, data: dict) -> GroupDevice:
    """Merge a partial `/ws/dali/groups` patch without dropping members or limits."""
    updates: dict[str, object] = {}
    if "dev_on" in data:
        updates["is_on"] = bool(data["dev_on"])
    if "level" in data:
        updates["stored_level"] = _as_optional_int(data["level"])
    if "dev_name" in data and data["dev_name"] not in (None, ""):
        updates["name"] = str(data["dev_name"]).strip()
    if "color_temp_k" in data:
        updates["color_temp_k"] = _as_optional_int(data["color_temp_k"])
    members = (
        _member_ids(data.get("members"))
        or _member_ids(data.get("lights"))
        or _member_ids(data.get("devices"))
    )
    if members:
        updates["members"] = members
    if not updates:
        return group
    return replace(group, **updates)


def apply_group_patches(
    groups: dict[str, GroupDevice], patches: list[tuple[str, dict]]
) -> dict[str, GroupDevice]:
    """Apply patches to known groups only. Unknown addrs are ignored."""
    if not patches:
        return groups
    updated = dict(groups)
    changed = False
    for addr, data in patches:
        current = updated.get(addr)
        if current is None:
            continue
        merged = apply_group_patch(current, data)
        if merged is not current:
            updated[addr] = merged
            changed = True
    return updated if changed else groups


def preserve_group_live_state(
    previous: dict[str, GroupDevice], discovered: dict[str, GroupDevice]
) -> dict[str, GroupDevice]:
    """Keep WebSocket group state when an HTTP poll omits on/level/members."""
    if not previous:
        return discovered
    merged: dict[str, GroupDevice] = {}
    for device_id, group in discovered.items():
        old = previous.get(device_id)
        if old is None:
            merged[device_id] = group
            continue
        updates: dict[str, object] = {}
        if group.is_on is None and old.is_on is not None:
            updates["is_on"] = old.is_on
        if group.stored_level is None and old.stored_level is not None:
            updates["stored_level"] = old.stored_level
        if group.color_temp_k is None and old.color_temp_k is not None:
            updates["color_temp_k"] = old.color_temp_k
        if not group.members and old.members:
            updates["members"] = old.members
        merged[device_id] = replace(group, **updates) if updates else group
    return merged

