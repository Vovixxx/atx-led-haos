"""Command table: every on/off call is one DAPC, preceded by colour frames when needed."""

from __future__ import annotations

from dataclasses import replace

import pytest

from atx_led.commands import group_members, plan_group, plan_light
from atx_led.models import GroupDevice, reconcile_lights


@pytest.fixture
def lights(addresses_payload: dict, devices_payload: dict) -> dict:
    return {x.device_id: x for x in reconcile_lights(addresses_payload, devices_payload)}


def _group(kind: str, members: tuple[str, ...], addr: int = 6, **extra) -> GroupDevice:
    values = dict(
        device_id=f"0_{'g' if kind == 'dali' else 'v'}_{addr}", channel=0, group_addr=addr,
        kind=kind, name="Group", is_on=True, stored_level=200, min_level=1, max_level=254,
        has_color_temp=True, color_temp_k=None, user_warm=370, user_cool=154,
        members=members,
    )
    values.update(extra)
    return GroupDevice(**values)


# 0_s_1: short addr 1, 2703-5000 K, level range 50-250; 0_s_21: 3003-6494 K; 0_s_11: no colour.

def test_light_on_with_colour_is_one_call_ending_in_dapc(lights) -> None:
    plan = plan_light(lights["0_s_1"], 250, 4000, None)
    assert plan.frames == {0: ["hA3FA", "hC300", "hC108", "h03E7", "h02FA"]}
    assert plan.colours == {"0_s_1": 4000}


def test_light_colour_is_clamped_to_its_range(lights) -> None:
    plan = plan_light(lights["0_s_1"], 250, 1800, None)
    # clamped to 2703 K = 370 mirek = 0x172
    assert plan.frames[0][:2] == ["hA372", "hC301"]
    assert plan.colours == {"0_s_1": 2703}


def test_light_on_without_colour_is_a_single_dapc(lights) -> None:
    assert plan_light(lights["0_s_1"], 120, None, None).frames == {0: ["h0278"]}


def test_light_colour_skipped_when_remembered_colour_matches(lights) -> None:
    plan = plan_light(lights["0_s_1"], 250, 4000, 4000)
    assert plan.frames == {0: ["h02FA"]}
    assert plan.colours == {"0_s_1": 4000}


def test_remembered_colour_from_a_driver_read_matches_by_mirek(lights) -> None:
    # 4004 K read back from a driver is the same mirek (250) as a requested 4000 K
    assert plan_light(lights["0_s_1"], 250, 4000, 4004).frames == {0: ["h02FA"]}


def test_light_without_colour_support_ignores_kelvin(lights) -> None:
    plan = plan_light(lights["0_s_11"], 100, 4000, None)
    assert plan.frames == {0: ["h1664"]}
    assert plan.colours == {}


def test_colour_support_for_unsigned_fixture_comes_from_the_override(lights) -> None:
    plain = replace(lights["0_s_11"], unsigned=True, has_color_temp=False)
    assert plan_light(plain, 100, 4000, None).frames == {0: ["h1664"]}
    tuned = replace(
        lights["0_s_11"], unsigned=True, has_color_temp=True, user_warm=370, user_cool=154
    )
    assert plan_light(tuned, 100, 4000, None).frames[0][3] == "h17E7"


def test_light_off_is_dapc_zero_and_no_colour(lights) -> None:
    plan = plan_light(lights["0_s_1"], 0, 4000, None)
    assert plan.frames == {0: ["h0200"]}
    assert plan.colours == {}


def test_colour_only_while_on_resends_the_current_level(lights) -> None:
    on = replace(lights["0_s_1"], is_on=True, stored_level=180)
    plan = plan_light(on, None, 4000, None)
    assert plan.frames[0][-1] == "h02B4"
    assert plan.frames[0][3] == "h03E7"


def test_dali_group_on_with_colour_matches_probe_golden(lights) -> None:
    group = _group("dali", ("0_s_1", "0_s_21"), user_warm=370, user_cool=154)
    plan = plan_group(group, lights, 253, 2700, {})
    assert plan.frames == {0: ["hA372", "hC301", "hC108", "h8DE7", "h8CFD"]}
    # the group range (2703 K warm end) clamps 2700 K for every member
    assert plan.colours == {"0_s_1": 2703, "0_s_21": 2703}


def test_dali_group_records_colour_on_colour_members_only(lights) -> None:
    group = _group("dali", ("0_s_1", "0_s_11", "0_s_21"))
    plan = plan_group(group, lights, 253, 4000, {})
    assert plan.colours == {"0_s_1": 4000, "0_s_21": 4000}


def test_dali_group_colour_skipped_when_all_colour_members_match(lights) -> None:
    group = _group("dali", ("0_s_1", "0_s_21"))
    remembered = {"0_s_1": 4000, "0_s_21": 4000}
    assert plan_group(group, lights, 253, 4000, remembered).frames == {0: ["h8CFD"]}
    remembered["0_s_21"] = 3500
    assert len(plan_group(group, lights, 253, 4000, remembered).frames[0]) == 5


def test_dali_group_without_colour_members_gets_single_dapc(lights) -> None:
    group = _group("dali", ("0_s_11",), has_color_temp=False)
    plan = plan_group(group, lights, 100, 4000, {})
    assert plan.frames == {0: ["h8C64"]}
    assert plan.colours == {}


def test_dali_group_off_and_colour_only_current_level(lights) -> None:
    group = _group("dali", ("0_s_1", "0_s_21"), stored_level=180)
    assert plan_group(group, lights, 0, None, {}).frames == {0: ["h8C00"]}
    colour_only = plan_group(group, lights, None, 4000, {})
    assert colour_only.frames[0][-1] == "h8CB4"


def test_virtual_group_sends_frames_per_member_in_member_order(lights) -> None:
    group = _group("virtual", ("0_s_1", "0_s_11", "0_s_21"), addr=0)
    plan = plan_group(group, lights, 200, 4000, {})
    assert plan.frames == {
        0: [
            "hA3FA", "hC300", "hC108", "h03E7", "h02C8",
            "h16C8",
            "hA3FA", "hC300", "hC108", "h2BE7", "h2AC8",
        ]
    }
    assert plan.colours == {"0_s_1": 4000, "0_s_21": 4000}


def test_virtual_group_skips_colour_per_member(lights) -> None:
    group = _group("virtual", ("0_s_1", "0_s_21"), addr=0)
    plan = plan_group(group, lights, 200, 4000, {"0_s_1": 4000})
    assert plan.frames == {0: ["h02C8", "hA3FA", "hC300", "hC108", "h2BE7", "h2AC8"]}


def test_virtual_group_spanning_channels_makes_one_list_per_channel(lights) -> None:
    other = replace(lights["0_s_21"], device_id="1_s_21", channel=1)
    lights = {**lights, "1_s_21": other}
    group = _group("virtual", ("0_s_1", "1_s_21"), addr=0)
    plan = plan_group(group, lights, 200, None, {})
    assert plan.frames == {0: ["h02C8"], 1: ["h2AC8"]}


def test_virtual_group_colour_only_uses_each_members_level(lights) -> None:
    a = replace(lights["0_s_1"], stored_level=100)
    b = replace(lights["0_s_21"], stored_level=150)
    group = _group("virtual", ("0_s_1", "0_s_21"), addr=0)
    plan = plan_group(group, {**lights, "0_s_1": a, "0_s_21": b}, None, None, {})
    assert plan.frames == {0: ["h0264", "h2A96"]}


def test_virtual_group_without_known_members_is_an_error(lights) -> None:
    with pytest.raises(ValueError):
        plan_group(_group("virtual", ("0_s_77",), addr=0), lights, 100, None, {})


def test_group_members_infers_from_membership_when_not_explicit(lights) -> None:
    group = _group("dali", (), addr=1)
    assert [m.device_id for m in group_members(group, lights)] == ["0_s_1"]
