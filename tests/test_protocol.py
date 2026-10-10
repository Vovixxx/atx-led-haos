from atx_led.protocol import (
    DaliReplyKind,
    command_frame,
    dapc_frame,
    decode_reply,
    decode_send_raw_payload,
    go_to_scene_frame,
    group_command_frame,
    group_dapc_frame,
    decode_colour_temperature_mirek,
    group_go_to_scene_frame,
    kelvin_to_mirek,
    mirek_to_kelvin,
    on_command_frames,
    query_colour_temperature_frames,
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


def test_group_on_frames_match_live_probe_golden() -> None:
    frames = on_command_frames(253, mirek=370, group_addr=6)
    assert frames == ["hA372", "hC301", "hC108", "h8DE7", "h8CFD"]


def test_short_address_on_frames_use_command_and_dapc_bytes() -> None:
    frames = on_command_frames(253, mirek=370, short_addr=31)
    assert frames == ["hA372", "hC301", "hC108", "h3FE7", "h3EFD"]


def test_on_frames_without_colour_are_a_single_dapc() -> None:
    assert on_command_frames(185, short_addr=1) == ["h02B9"]
    assert on_command_frames(0, group_addr=1) == ["h8200"]


def test_on_frames_need_exactly_one_target() -> None:
    import pytest

    with pytest.raises(ValueError):
        on_command_frames(100)
    with pytest.raises(ValueError):
        on_command_frames(100, short_addr=1, group_addr=1)


def test_kelvin_to_mirek_rounds() -> None:
    assert kelvin_to_mirek(2700) == 370
    assert kelvin_to_mirek(4000) == 250
    assert kelvin_to_mirek(6500) == 154


def test_kelvin_to_mirek_clamps_kelvin_to_the_light_range() -> None:
    assert kelvin_to_mirek(1000, 2700, 6500) == 370
    assert kelvin_to_mirek(9000, 2700, 6500) == 154
    assert kelvin_to_mirek(4000, 2700, 6500) == 250


def test_mirek_to_kelvin_rounds_and_rejects_zero() -> None:
    assert mirek_to_kelvin(370) == 2703
    assert mirek_to_kelvin(0) is None


def test_colour_query_frames_read_msb_then_lsb() -> None:
    assert query_colour_temperature_frames(17) == ["hA302", "hC108", "h23FA", "h2398"]


def test_decode_colour_temperature_reply() -> None:
    reply = decode_send_raw_payload({"ok": True, "responses": ["N", "N", "J01", "J72"]})
    assert decode_colour_temperature_mirek(reply) == 370


def test_decode_colour_temperature_reply_unusable() -> None:
    no_answer = decode_send_raw_payload({"ok": True, "responses": ["N", "N", "N", "N"]})
    assert decode_colour_temperature_mirek(no_answer) is None
    mask = decode_send_raw_payload({"ok": True, "responses": ["N", "N", "JFF", "JFF"]})
    assert decode_colour_temperature_mirek(mask) is None
