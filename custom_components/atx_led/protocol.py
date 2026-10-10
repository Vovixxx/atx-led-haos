"""DALI frame encoding and ATX LED send-raw reply decoding."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

DALI_MAX_ARC_LEVEL = 254
DALI_MASK_LEVEL = 255
SHORT_ADDR_MAX = 63
GROUP_ADDR_MAX = 15
SCENE_MAX = 15

QUERY_STATUS = 0x90
QUERY_ACTUAL_LEVEL = 0xA0
QUERY_MAX_LEVEL = 0xA1
QUERY_MIN_LEVEL = 0xA2
QUERY_CONTENT_DTR0 = 0x98
GO_TO_SCENE = 0x10

# DALI-2 part 209 (DT8) colour control, sent as special/device-type commands.
SET_DTR0 = 0xA3
SET_DTR1 = 0xC3
ENABLE_DEVICE_TYPE = 0xC1
DEVICE_TYPE_COLOUR = 0x08
SET_TEMPORARY_COLOUR_TEMPERATURE = 0xE7
QUERY_COLOUR_VALUE = 0xFA
COLOUR_VALUE_SELECTOR_TC = 0x02
MIREK_MASK = 0xFFFF


class DaliReplyKind(Enum):
    BYTE = "byte"
    NO_REPLY = "no_reply"
    COLLISION = "collision"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DaliReply:
    kind: DaliReplyKind
    raw: str
    value: int | None = None


@dataclass(frozen=True)
class SendRawResult:
    ok: bool
    responses: tuple[DaliReply, ...]


def _require_short_addr(short_addr: int) -> int:
    if not 0 <= short_addr <= SHORT_ADDR_MAX:
        raise ValueError(f"DALI short address must be 0-63, got {short_addr}")
    return short_addr


def dapc_frame(short_addr: int, level: int) -> str:
    """Encode a Direct Arc Power Control frame as an ATX `hXXXX` command."""
    _require_short_addr(short_addr)
    level = max(0, min(int(level), DALI_MAX_ARC_LEVEL))
    return f"h{short_addr * 2:02X}{level:02X}"


def command_frame(short_addr: int, opcode: int) -> str:
    """Encode a DALI command/query frame as an ATX `hXXXX` command."""
    _require_short_addr(short_addr)
    opcode = int(opcode) & 0xFF
    return f"h{short_addr * 2 + 1:02X}{opcode:02X}"


def _require_group_addr(group_addr: int) -> int:
    if not 0 <= group_addr <= GROUP_ADDR_MAX:
        raise ValueError(f"DALI group address must be 0-15, got {group_addr}")
    return group_addr


def _require_scene(scene: int) -> int:
    if not 0 <= scene <= SCENE_MAX:
        raise ValueError(f"DALI scene must be 0-15, got {scene}")
    return scene


def group_dapc_frame(group_addr: int, level: int) -> str:
    """Encode a group Direct Arc Power Control frame as an ATX `hXXXX` command.

    HAT docs: group DAPC address byte is ``group * 2 + 0x80`` (0x80–0x9E).
    """
    _require_group_addr(group_addr)
    level = max(0, min(int(level), DALI_MAX_ARC_LEVEL))
    return f"h{0x80 + group_addr * 2:02X}{level:02X}"


def group_command_frame(group_addr: int, opcode: int) -> str:
    """Encode a DALI group command frame as an ATX `hXXXX` command.

    HAT docs: group command address byte is ``group * 2 + 0x81`` (0x81–0x9F).
    """
    _require_group_addr(group_addr)
    opcode = int(opcode) & 0xFF
    return f"h{0x80 + group_addr * 2 + 1:02X}{opcode:02X}"


def go_to_scene_opcode(scene: int) -> int:
    """Return the DALI GO TO SCENE opcode for scene 0-15 (0x10-0x1F)."""
    return GO_TO_SCENE + _require_scene(scene)


def go_to_scene_frame(short_addr: int, scene: int) -> str:
    """Recall a DALI scene on one short address. Does not use broadcast."""
    return command_frame(short_addr, go_to_scene_opcode(scene))


def group_go_to_scene_frame(group_addr: int, scene: int) -> str:
    """Recall a DALI scene on one group. Does not use broadcast."""
    return group_command_frame(group_addr, go_to_scene_opcode(scene))


def query_status_level_max_min(short_addr: int) -> list[str]:
    """Read-only status, actual level, max, and min queries for one fixture."""
    return [
        command_frame(short_addr, QUERY_STATUS),
        command_frame(short_addr, QUERY_ACTUAL_LEVEL),
        command_frame(short_addr, QUERY_MAX_LEVEL),
        command_frame(short_addr, QUERY_MIN_LEVEL),
    ]


def decode_reply(token: str) -> DaliReply:
    raw = str(token).strip()
    if raw == "N":
        return DaliReply(DaliReplyKind.NO_REPLY, raw)
    if raw in {"X", "Z"}:
        return DaliReply(DaliReplyKind.COLLISION, raw)
    if len(raw) == 3 and raw[0] in {"J", "j"}:
        try:
            return DaliReply(DaliReplyKind.BYTE, raw, int(raw[1:], 16))
        except ValueError:
            return DaliReply(DaliReplyKind.UNKNOWN, raw)
    return DaliReply(DaliReplyKind.UNKNOWN, raw)


def decode_send_raw_payload(payload: dict) -> SendRawResult:
    responses = tuple(decode_reply(item) for item in payload.get("responses", []))
    return SendRawResult(ok=bool(payload.get("ok")), responses=responses)


def kelvin_to_mirek(
    kelvin: int, kelvin_min: int | None = None, kelvin_max: int | None = None
) -> int:
    """Convert Kelvin to a DT8 mirek value, clamping Kelvin to the light's range first."""
    kelvin = int(kelvin)
    if kelvin_min and kelvin_max:
        kelvin = max(kelvin_min, min(kelvin, kelvin_max))
    if kelvin <= 0:
        raise ValueError(f"Color temperature must be positive, got {kelvin}")
    return max(1, min(round(1_000_000 / kelvin), MIREK_MASK - 1))


def mirek_to_kelvin(mirek: int) -> int | None:
    if mirek <= 0:
        return None
    return round(1_000_000 / mirek)


def on_command_frames(
    level: int,
    *,
    mirek: int | None = None,
    short_addr: int | None = None,
    group_addr: int | None = None,
) -> list[str]:
    """Frames for one on/off/level call on a fixture or a DALI group.

    With ``mirek`` the temporary colour (DTR0 LSB, DTR1 MSB, ENABLE DEVICE TYPE 8,
    SET TEMPORARY COLOUR TEMPERATURE) comes first, and the final DAPC applies level
    and colour in one fade. Without it the call is a single DAPC.
    """
    if (short_addr is None) == (group_addr is None):
        raise ValueError("Give exactly one of short_addr or group_addr")
    frames: list[str] = []
    if mirek is not None:
        mirek = max(0, min(int(mirek), MIREK_MASK - 1))
        frames.extend(
            [
                f"h{SET_DTR0:02X}{mirek & 0xFF:02X}",
                f"h{SET_DTR1:02X}{mirek >> 8:02X}",
                f"h{ENABLE_DEVICE_TYPE:02X}{DEVICE_TYPE_COLOUR:02X}",
            ]
        )
        if short_addr is not None:
            frames.append(command_frame(short_addr, SET_TEMPORARY_COLOUR_TEMPERATURE))
        else:
            frames.append(group_command_frame(group_addr, SET_TEMPORARY_COLOUR_TEMPERATURE))
    if short_addr is not None:
        frames.append(dapc_frame(short_addr, level))
    else:
        frames.append(group_dapc_frame(group_addr, level))
    return frames


def query_colour_temperature_frames(short_addr: int) -> list[str]:
    """Read-only DT8 QUERY COLOUR VALUE (selector 2): reply 3 is MSB, reply 4 is LSB."""
    return [
        f"h{SET_DTR0:02X}{COLOUR_VALUE_SELECTOR_TC:02X}",
        f"h{ENABLE_DEVICE_TYPE:02X}{DEVICE_TYPE_COLOUR:02X}",
        command_frame(short_addr, QUERY_COLOUR_VALUE),
        command_frame(short_addr, QUERY_CONTENT_DTR0),
    ]


def decode_colour_temperature_mirek(result: SendRawResult) -> int | None:
    """Mirek from a ``query_colour_temperature_frames`` reply, or None if unusable."""
    if len(result.responses) < 4:
        return None
    msb, lsb = result.responses[2], result.responses[3]
    if msb.kind is not DaliReplyKind.BYTE or lsb.kind is not DaliReplyKind.BYTE:
        return None
    mirek = (msb.value << 8) | lsb.value
    if mirek in (0, MIREK_MASK):
        return None
    return mirek
