"""Plan the send-raw frames for one on/off/colour call.

Every call ends in DAPC; when the colour has to change, temporary-colour frames
come first so the one fade applies level and colour together.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import GroupDevice, LightDevice, color_temp_range_kelvin
from .protocol import DALI_MAX_ARC_LEVEL, kelvin_to_mirek, on_command_frames


@dataclass(frozen=True)
class CommandPlan:
    """Frames per DALI channel, and the colour (Kelvin) each fixture will hold."""

    frames: dict[int, list[str]] = field(default_factory=dict)
    colours: dict[str, int] = field(default_factory=dict)


def kelvin_limits(device: LightDevice | GroupDevice) -> tuple[int, int] | None:
    minimum, maximum = color_temp_range_kelvin(device.user_warm, device.user_cool)
    if minimum and maximum:
        return (minimum, maximum)
    return None


def _clamped_kelvin(device: LightDevice | GroupDevice, kelvin: int) -> int:
    limits = kelvin_limits(device)
    if limits:
        return max(limits[0], min(int(kelvin), limits[1]))
    return int(kelvin)


def _current_level(device: LightDevice | GroupDevice) -> int:
    if device.stored_level and device.stored_level > 0:
        return min(device.stored_level, DALI_MAX_ARC_LEVEL)
    return min(device.max_level, DALI_MAX_ARC_LEVEL)


def _same_colour(first: int | None, second: int) -> bool:
    return first is not None and kelvin_to_mirek(first) == kelvin_to_mirek(second)


def group_members(group: GroupDevice, lights: dict[str, LightDevice]) -> list[LightDevice]:
    """Known fixtures in a group, in member order (DALI groups fall back to membership bits)."""
    members = [lights[member_id] for member_id in group.members if member_id in lights]
    if not members and group.is_dali_group and not group.members_explicit:
        members = [
            light
            for light in lights.values()
            if light.channel == group.channel and group.group_addr in light.group_membership
        ]
    return members


def plan_light(
    light: LightDevice, level: int | None, kelvin: int | None, remembered_kelvin: int | None
) -> CommandPlan:
    """One fixture. ``level`` None keeps the current level (colour-only call)."""
    if level is None:
        level = _current_level(light)
    mirek = None
    colours: dict[str, int] = {}
    if kelvin is not None and light.has_color_temp and level > 0:
        target = _clamped_kelvin(light, kelvin)
        colours[light.device_id] = target
        if not _same_colour(remembered_kelvin, target):
            mirek = kelvin_to_mirek(target)
    frames = on_command_frames(level, mirek=mirek, short_addr=light.short_addr)
    return CommandPlan({light.channel: frames}, colours)


def plan_group(
    group: GroupDevice,
    lights: dict[str, LightDevice],
    level: int | None,
    kelvin: int | None,
    remembered: dict[str, int],
) -> CommandPlan:
    """A DALI group (one frame set on the group address) or a virtual group (per member)."""
    members = group_members(group, lights)
    if group.is_dali_group:
        if level is None:
            level = _current_level(group)
        mirek = None
        colours: dict[str, int] = {}
        colour_members = [member for member in members if member.has_color_temp]
        if kelvin is not None and colour_members and level > 0:
            target = _clamped_kelvin(group, kelvin)
            colours = {member.device_id: target for member in colour_members}
            if not all(
                _same_colour(remembered.get(member.device_id), target)
                for member in colour_members
            ):
                mirek = kelvin_to_mirek(target)
        frames = on_command_frames(level, mirek=mirek, group_addr=group.group_addr)
        return CommandPlan({group.channel: frames}, colours)
    if not members:
        raise ValueError("Group has no known member lights")
    frames_by_channel: dict[int, list[str]] = {}
    colours = {}
    for member in members:
        plan = plan_light(member, level, kelvin, remembered.get(member.device_id))
        for channel, frames in plan.frames.items():
            frames_by_channel.setdefault(channel, []).extend(frames)
        colours.update(plan.colours)
    return CommandPlan(frames_by_channel, colours)
