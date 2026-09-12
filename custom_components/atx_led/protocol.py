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
GO_TO_SCENE = 0x10


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
