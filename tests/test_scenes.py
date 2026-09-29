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


def test_numeric_scene_members_use_scene_channel() -> None:
    scene = parse_scenes({"1_sc_4": {"scene": 4, "members": [3]}})[0]
    assert scene.members == ("1_s_3",)


def test_atx_hub_snapshot_is_not_mistaken_for_dali_scene_slot() -> None:
    scenes = parse_scenes(
        {
            "0": {
                "id": 0,
                "name": "Scene 0",
                "visible": True,
                "state": {
                    "0_s_1": {"dev_on": True, "level": 253},
                    "0_s_11": {"dev_on": False, "level": 0},
                },
            },
            "1": {
                "id": 1,
                "name": "Test Scene",
                "state": {"0_s_11": {"dev_on": True, "level": 133}},
            },
        }
    )
    assert [(scene.name, scene.hub_scene_id) for scene in scenes] == [
        ("Scene 0", "0"),
        ("Test Scene", "1"),
    ]
    assert scenes[0].members == ("0_s_1", "0_s_11")
    assert scenes[0].channel == 0
    assert scenes[0].dali_scene is None


def test_list_scene_zero_keeps_identity_across_rename() -> None:
    state = {"0_s_1": {"dev_on": True, "level": 100}}
    before = parse_scenes([{"id": 0, "name": "Scene 0", "state": state}])[0]
    after = parse_scenes([{"id": 0, "name": "Evening", "state": state}])[0]

    assert before.scene_id == after.scene_id == "0"
    assert before.unique_suffix == after.unique_suffix == "scene_0"
    assert before.hub_scene_id == after.hub_scene_id == "0"
    assert after.name == "Evening"


def test_list_scene_accepts_other_numeric_ids_and_ignores_invalid_ids() -> None:
    scenes = parse_scenes([
        {"id": 2, "name": "Two", "state": {}},
        {"id": "03", "name": "Three", "state": {}},
        {"id": -1, "name": "Invalid", "state": {}},
        {"id": True, "name": "Boolean", "state": {}},
        {"name": "Missing", "state": {}},
        {"id": -1, "state": {}},
        {"name": "123", "state": {}},
    ])
    assert [(scene.scene_id, scene.hub_scene_id) for scene in scenes] == [
        ("2", "2"), ("3", "3"), ("Invalid", None),
        ("Boolean", None), ("Missing", None), ("5", None), ("123", None),
    ]


def test_list_scene_preserves_named_dali_id() -> None:
    scene = parse_scenes([{"id": "1_sc_4", "name": "Upstairs", "members": [3]}])[0]
    assert scene.scene_id == "1_sc_4"
    assert scene.unique_suffix == "scene_1_sc_4"
    assert scene.channel == 1
    assert scene.dali_scene == 4
    assert scene.members == ("1_s_3",)
