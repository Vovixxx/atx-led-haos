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
    state_source: str = "unknown"

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


def _preferred_name(*candidates: object, fallback: str) -> str:
    """Pick the first non-empty label. Prefer Hue/user names over generic Group N."""
    for candidate in candidates:
        if candidate is None or candidate is False:
            continue
        text = str(candidate).strip()
        if text:
            return text
    return fallback


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
    name = _preferred_name(raw.get("hue_name"), raw.get("dev_name"), fallback=device_id)
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


def _membership_from_item(item: object) -> list[int]:
    if isinstance(item, bool):
        return []
    parsed = _as_optional_int(item)
    if parsed is not None:
        return [parsed] if 0 <= parsed <= GROUP_ADDR_MAX else []
    if isinstance(item, str):
        addr = parse_addr_id(item)
        if addr is not None and addr[1] == "g" and 0 <= addr[2] <= GROUP_ADDR_MAX:
            return [addr[2]]
        return []
    if isinstance(item, dict):
        if item.get("key"):
            return _membership_from_item(item["key"])
        for key in ("group", "group_addr"):
            if key in item:
                return _membership_from_item(item[key])
    return []


def _parse_group_membership(value: object) -> tuple[int, ...]:
    if isinstance(value, list):
        if len(value) == GROUP_ADDR_MAX + 1 and all(item in (0, 1, True, False) for item in value):
            return tuple(
                index for index, item in enumerate(value) if item not in (0, False, None)
            )
        groups: list[int] = []
        for item in value:
            for group_addr in _membership_from_item(item):
                if group_addr not in groups:
                    groups.append(group_addr)
        return tuple(groups)
    if isinstance(value, dict):
        groups: list[int] = []
        for key, item in value.items():
            if item in (False, 0, None, ""):
                continue
            for group_addr in _membership_from_item(key):
                if group_addr not in groups:
                    groups.append(group_addr)
            if item not in (True, 1):
                for group_addr in _membership_from_item(item):
                    if group_addr not in groups:
                        groups.append(group_addr)
        return tuple(groups)
    if isinstance(value, str):
        return tuple(_membership_from_item(value))
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


def _member_ids(value: object, channel: int = 0) -> tuple[str, ...]:
    if isinstance(value, list):
        members: list[str] = []
        for item in value:
            if isinstance(item, str) and item and item not in members:
                members.append(item)
            elif isinstance(item, dict) and item.get("key"):
                key = str(item["key"])
                if key and key not in members:
                    members.append(key)
            else:
                short_addr = _as_optional_int(item)
                if short_addr is None or not 0 <= short_addr <= SHORT_ADDR_MAX:
                    continue
                member_id = f"{channel}_s_{short_addr}"
                if member_id not in members:
                    members.append(member_id)
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
        name = _preferred_name(
            raw.get("hue_name"), raw.get("dev_name"), name_fallback, fallback=device_id
        )
        is_on_raw = raw.get("dev_on")
        is_on = None if is_on_raw is None else bool(is_on_raw)
        members = (
            _member_ids(raw.get("members"), channel)
            or _member_ids(raw.get("lights"), channel)
            or _member_ids(raw.get("devices"), channel)
            or _member_ids(raw.get("device_ids"), channel)
        )
        stored_level = _as_optional_int(raw.get("level"))
        return GroupDevice(
            device_id=device_id,
            channel=channel,
            group_addr=group_addr if group_addr is not None else 0,
            kind=kind,
            name=name,
            is_on=is_on,
            stored_level=stored_level,
            min_level=_as_int(raw.get("min_level"), 1),
            max_level=_as_int(raw.get("max_level"), 254),
            has_color_temp=_as_bool(raw.get("has_color_temp")),
            color_temp_k=_as_optional_int(raw.get("color_temp_k")),
            user_warm=_as_optional_int(raw.get("user_warm")),
            user_cool=_as_optional_int(raw.get("user_cool")),
            members=members,
            state_source="hub" if is_on is not None or stored_level is not None else "unknown",
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
        state_source="unknown",
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


def _group_device_record(
    devices: dict, device_id: str, channel: int | None, group_addr: int | None
) -> dict | None:
    """Find a group record under the hub id or a few observed alternate keys."""
    parsed_id = parse_addr_id(device_id)
    marker = parsed_id[1] if parsed_id is not None else None
    if marker not in {"g", "v"}:
        marker = None
    candidates = [device_id]
    if parsed_id is not None:
        channel = parsed_id[0] if channel is None else channel
        group_addr = parsed_id[2] if group_addr is None else group_addr
    if marker is not None and channel is not None and group_addr is not None:
        candidates.append(f"{channel}_{marker}_{group_addr}")
    for key in candidates:
        raw = devices.get(key)
        if isinstance(raw, dict):
            return raw
    if channel is None or group_addr is None:
        return None
    wanted_address = {"group", "g"} if marker == "g" else {"virtual", "v"} if marker == "v" else set()
    for key, raw in devices.items():
        if not isinstance(raw, dict):
            continue
        parsed = parse_addr_id(str(key))
        if (
            parsed is not None
            and parsed[0] == channel
            and parsed[2] == group_addr
            and (marker is None or parsed[1] == marker)
            and parsed[1] in {"g", "v"}
        ):
            return raw
        address = raw.get("address")
        if (
            wanted_address
            and isinstance(address, list)
            and len(address) >= 3
            and address[1] in wanted_address
            and _as_optional_int(address[2]) == group_addr
            and _as_int(raw.get("channel"), channel) == channel
        ):
            return raw
    return None


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
            parsed = parse_addr_id(device_id)
            raw = _group_device_record(
                devices,
                device_id,
                parsed[0] if parsed else None,
                parsed[2] if parsed else None,
            )
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
        result = [derive_group_state(group, {light.device_id: light for light in lights}) for group in result]
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
    if data.get("hue_name") not in (None, ""):
        updates["name"] = str(data["hue_name"]).strip()
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
        updates["state_source"] = "hub"
    if "level" in data:
        updates["stored_level"] = _as_optional_int(data["level"])
        updates["state_source"] = "hub"
    if "dev_name" in data and data["dev_name"] not in (None, ""):
        updates["name"] = str(data["dev_name"]).strip()
    if data.get("hue_name") not in (None, ""):
        updates["name"] = str(data["hue_name"]).strip()
    if "color_temp_k" in data:
        updates["color_temp_k"] = _as_optional_int(data["color_temp_k"])
    members = (
        _member_ids(data.get("members"), group.channel)
        or _member_ids(data.get("lights"), group.channel)
        or _member_ids(data.get("devices"), group.channel)
        or _member_ids(data.get("device_ids"), group.channel)
    )
    if members:
        updates["members"] = members
    if not updates:
        return group
    return replace(group, **updates)


def _resolve_group_patch_id(addr: str, groups: dict[str, GroupDevice]) -> str | None:
    if addr in groups:
        return addr
    parsed = parse_addr_id(addr)
    if parsed is None or parsed[1] not in {"g", "v"}:
        return None
    channel, marker, group_addr = parsed
    kind = GROUP_KIND_DALI if marker == "g" else GROUP_KIND_VIRTUAL
    for device_id, group in groups.items():
        if group.channel == channel and group.group_addr == group_addr and group.kind == kind:
            return device_id
    return None


def apply_group_patches(
    groups: dict[str, GroupDevice], patches: list[tuple[str, dict]]
) -> dict[str, GroupDevice]:
    """Apply patches to known groups only. Unknown addrs are ignored."""
    if not patches:
        return groups
    updated = dict(groups)
    changed = False
    for addr, data in patches:
        device_id = _resolve_group_patch_id(addr, updated)
        if device_id is None:
            continue
        current = updated[device_id]
        merged = apply_group_patch(current, data)
        if merged is not current:
            updated[device_id] = merged
            changed = True
    return updated if changed else groups


def derive_group_state(
    group: GroupDevice, lights: dict[str, LightDevice]
) -> GroupDevice:
    """Fill missing group on/level/CCT from member fixtures. Hub on/level win."""
    members = [lights[member_id] for member_id in group.members if member_id in lights]
    if not members and group.is_dali_group:
        members = [
            light
            for light in lights.values()
            if light.channel == group.channel and group.group_addr in light.group_membership
        ]
    updates: dict[str, object] = {}
    if members and not group.members:
        updates["members"] = tuple(light.device_id for light in members)
    known = [light.is_on for light in members if light.is_on is not None]
    any_on = any(known) if known else None
    if any_on:
        if group.is_on is not True:
            updates["is_on"] = True
            if group.state_source != "hub":
                updates["state_source"] = "derived"
        on_levels = [
            light.stored_level
            for light in members
            if light.is_on and light.stored_level is not None
        ]
        if on_levels and group.stored_level != max(on_levels):
            updates["stored_level"] = max(on_levels)
            if group.state_source != "hub":
                updates.setdefault("state_source", "derived")
    elif group.state_source != "hub":
        if known and group.is_on is not False:
            updates["is_on"] = False
            updates["state_source"] = "derived"
        levels = [
            light.stored_level
            for light in members
            if light.stored_level is not None
        ]
        if levels and (group.stored_level is None or group.stored_level != max(levels)):
            updates["stored_level"] = max(levels)
            updates.setdefault("state_source", "derived")
        if members:
            new_min = min(light.min_level for light in members)
            new_max = max(light.max_level for light in members)
            if new_min != group.min_level:
                updates["min_level"] = new_min
            if new_max != group.max_level:
                updates["max_level"] = new_max
    updates.update(_derive_group_color_temp(group, members))
    if not updates:
        return group
    return replace(group, **updates)


def _derive_group_color_temp(
    group: GroupDevice, members: list[LightDevice]
) -> dict[str, object]:
    """Expose CCT on a group when member fixtures advertise it.

    Hub group records often store ``color_temp_k`` without ``has_color_temp``.
    Slider bounds are the intersection of member user ranges so the same
    Kelvin is valid on every color-temp fixture in the group.
    """
    cct_members = [light for light in members if light.has_color_temp]
    if not cct_members:
        return {}
    updates: dict[str, object] = {}
    if not group.has_color_temp:
        updates["has_color_temp"] = True
    if group.color_temp_k is None:
        kelvin_values = [
            light.color_temp_k for light in cct_members if light.color_temp_k is not None
        ]
        if kelvin_values:
            updates["color_temp_k"] = kelvin_values[0]
    if not group.user_warm or not group.user_cool:
        ranges = [
            color_temp_range_kelvin(light.user_warm, light.user_cool)
            for light in cct_members
        ]
        usable = [
            (minimum, maximum)
            for minimum, maximum in ranges
            if minimum is not None and maximum is not None
        ]
        if usable:
            min_k = max(minimum for minimum, _maximum in usable)
            max_k = min(maximum for _minimum, maximum in usable)
            if min_k < max_k:
                updates["user_warm"] = round(1_000_000 / min_k)
                updates["user_cool"] = round(1_000_000 / max_k)
    return updates


def apply_derived_group_states(
    groups: dict[str, GroupDevice], lights: dict[str, LightDevice]
) -> dict[str, GroupDevice]:
    """Refresh derived group state after fixture or inventory updates."""
    if not groups:
        return groups
    updated = dict(groups)
    changed = False
    for device_id, group in groups.items():
        merged = derive_group_state(group, lights)
        if merged is not group:
            updated[device_id] = merged
            changed = True
    return updated if changed else groups


def merge_group_records(devices: dict, groups_payload: object) -> dict:
    """Copy best-effort `/dali/api/groups` records into the devices map."""
    if not isinstance(devices, dict):
        devices = {}
    if not isinstance(groups_payload, dict):
        return devices
    merged = dict(devices)
    changed = False
    for key, raw in groups_payload.items():
        if str(key) in {"ok", "Groups", "groups"}:
            continue
        if not isinstance(raw, dict) or key in merged:
            continue
        merged[key] = raw
        changed = True
    nested = groups_payload.get("Groups") or groups_payload.get("groups")
    if isinstance(nested, dict):
        extra = merge_group_records(merged, nested)
        return extra
    return merged if changed else devices


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
        if old.state_source == "hub" and group.state_source != "hub":
            updates["is_on"] = old.is_on
            updates["stored_level"] = old.stored_level
            updates["color_temp_k"] = old.color_temp_k
            updates["state_source"] = "hub"
        else:
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

