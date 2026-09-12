from atx_led.models import parse_scenes, reconcile_lights, scene_short_addrs


def test_parse_scenes_object_payload(scenes_payload: dict) -> None:
    scenes = parse_scenes(scenes_payload)
    assert [scene.scene_id for scene in scenes] == ["0_sc_0", "0_sc_1"]
    evening = scenes[0]
    assert evening.name == "Evening"
    assert evening.channel == 0
    assert evening.dali_scene == 0
    assert evening.members == ("0_s_1", "0_s_11")
    night = scenes[1]
    assert night.dali_scene == 1
    assert night.group_addr == 1


def test_parse_scenes_key_value_list() -> None:
    scenes = parse_scenes(
        {"Scenes": [{"key": "0_sc_2", "value": "Movie", "scene": 2, "channel": 0}]}
    )
    assert len(scenes) == 1
    assert scenes[0].name == "Movie"
    assert scenes[0].dali_scene == 2


def test_parse_scenes_ignores_malformed_payloads() -> None:
    assert parse_scenes("not-json") == []
    assert parse_scenes(None) == []
    assert parse_scenes({"ok": True}) == []


def test_parse_scenes_nested_object_and_ok_wrapper() -> None:
    nested = parse_scenes(
        {"scenes": {"0_sc_0": {"dev_name": "Evening", "scene": 0, "channel": 0}}}
    )
    assert [scene.scene_id for scene in nested] == ["0_sc_0"]
    wrapped = parse_scenes(
        {"ok": True, "scenes": [{"key": "0_sc_3", "value": "Read", "scene": 3}]}
    )
    assert wrapped[0].dali_scene == 3
    assert wrapped[0].name == "Read"


def test_scene_short_addr_is_not_treated_as_group() -> None:
    scenes = parse_scenes(
        {"0_sc_0": {"dev_name": "Evening", "scene": 0, "short_addr": 1, "channel": 0}}
    )
    assert scenes[0].group_addr is None
    assert scenes[0].dali_scene == 0


def test_scene_short_addrs_skip_groups_and_unknowns(
    addresses_payload: dict, devices_payload: dict
) -> None:
    lights = {
        light.device_id: light
        for light in reconcile_lights(addresses_payload, devices_payload)
    }
    addrs = scene_short_addrs(("0_s_1", "0_g_1", "0_s_99", "0_s_11"), lights)
    assert addrs == [1, 11]


def test_scene_id_can_supply_channel_and_number() -> None:
    scenes = parse_scenes([{"key": "1_sc_4", "value": "Upstairs"}])
    assert scenes[0].channel == 1
    assert scenes[0].dali_scene == 4
