from atx_led.protocol import (
    DaliReplyKind,
    command_frame,
    dapc_frame,
    decode_reply,
    decode_send_raw_payload,
    go_to_scene_frame,
    group_command_frame,
    group_dapc_frame,
    group_go_to_scene_frame,
    query_status_level_max_min,
)


def test_dapc_frame_matches_verified_address_1_level_185() -> None:
    assert dapc_frame(short_addr=1, level=185) == "h02B9"


def test_dapc_frame_off_is_level_zero() -> None:
    assert dapc_frame(short_addr=1, level=0) == "h0200"


def test_dapc_frame_rejects_mask_level() -> None:
    assert dapc_frame(short_addr=1, level=255) == "h02FE"


def test_command_frame_uses_odd_address_byte() -> None:
    assert command_frame(short_addr=1, opcode=0x90) == "h0390"


def test_query_bundle_matches_verified_read_only_request() -> None:
    assert query_status_level_max_min(1) == ["h0390", "h03A0", "h03A1", "h03A2"]


def test_decode_verified_address_1_readback() -> None:
    payload = {"ok": True, "responses": ["J00", "J00", "JFA", "J32"]}
    result = decode_send_raw_payload(payload)
    assert result.ok is True
    assert [item.value for item in result.responses] == [0, 0, 250, 50]
    assert all(item.kind is DaliReplyKind.BYTE for item in result.responses)


def test_decode_no_reply_is_not_zero() -> None:
    reply = decode_reply("N")
    assert reply.kind is DaliReplyKind.NO_REPLY
    assert reply.value is None


def test_decode_collision_is_not_zero() -> None:
    assert decode_reply("X").kind is DaliReplyKind.COLLISION
    assert decode_reply("Z").kind is DaliReplyKind.COLLISION
    assert decode_reply("X").value is None


def test_dapc_rejects_invalid_short_address() -> None:
    try:
        dapc_frame(short_addr=64, level=1)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_group_dapc_matches_hat_addressing() -> None:
    assert group_dapc_frame(group_addr=0, level=0) == "h8000"
    assert group_dapc_frame(group_addr=1, level=185) == "h82B9"
    assert group_dapc_frame(group_addr=15, level=254) == "h9EFE"


def test_group_command_frame_uses_odd_group_address_byte() -> None:
    assert group_command_frame(group_addr=0, opcode=0x10) == "h8110"
    assert group_go_to_scene_frame(group_addr=1, scene=3) == "h8313"


def test_go_to_scene_uses_individual_command_not_broadcast() -> None:
    assert go_to_scene_frame(short_addr=1, scene=0) == "h0310"
    assert not go_to_scene_frame(short_addr=1, scene=0).startswith("hFF")


def test_group_frames_reject_invalid_group() -> None:
    try:
        group_dapc_frame(group_addr=16, level=1)
    except ValueError:
        return
    raise AssertionError("expected ValueError")
