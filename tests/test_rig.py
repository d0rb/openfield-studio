import json

import pytest

from openfield.engine import rig
from openfield.engine.rig import CameraRig, compile_prompt, compile_shot


def test_exactly_35_unique_moves_in_known_groups():
    assert len(rig.MOVES) == 35
    assert {m.group for m in rig.MOVES.values()} <= set(rig.GROUPS)
    assert {m.mode for m in rig.MOVES.values()} <= {"keyframed", "prompt_only", "experimental"}
    # every group is reachable from the Move Pad
    assert {m.group for m in rig.MOVES.values()} == set(rig.GROUPS)


def test_at_most_twelve_moves_are_promoted_and_none_is_experimental():
    featured = [m for m in rig.MOVES.values() if m.featured]
    assert 1 <= len(featured) <= 12
    assert all(m.mode != "experimental" for m in featured)


def test_keyframed_moves_carry_the_edits_their_anchors_need():
    for move in rig.MOVES.values():
        if move.mode != "keyframed":
            assert move.anchors == 1 and not move.edits
            continue
        needed = move.anchors - 2 if move.id == "orbit_360" else move.anchors - 1
        assert len(move.edits) == needed, move.id


def test_paths_are_geometrically_sensible():
    dolly_in = rig.MOVES["dolly_in"].path()
    assert dolly_in[-1].z > dolly_in[0].z  # camera ends closer to the subject
    pull = rig.MOVES["dolly_out"].path()
    assert pull[-1].z < pull[0].z
    orbit90 = rig.MOVES["orbit_90"].path()
    assert orbit90[-1].x == pytest.approx(1.0, abs=1e-6) and orbit90[-1].z == pytest.approx(0.0, abs=1e-6)
    orbit360 = rig.MOVES["orbit_360"].path()
    assert orbit360[-1].x == pytest.approx(orbit360[0].x, abs=1e-6)
    assert orbit360[-1].z == pytest.approx(orbit360[0].z, abs=1e-6)
    assert rig.MOVES["optical_zoom_in"].path()[-1].fov < 40
    assert len(rig.MOVES["static"].path()) == 2


def test_catalog_is_json_serialisable_and_complete():
    data = json.loads(json.dumps(rig.catalog()))
    assert len(data["moves"]) == 35
    assert data["moves"][0]["path"] and "group_label" in data["moves"][0]
    assert "anamorphic" in data["options"]["lens"]


def test_prompt_is_one_clean_paragraph_with_the_constraint():
    text = compile_prompt(CameraRig(movement="orbit_90"), "A glass perfume bottle on marble.")
    assert text.startswith("A glass perfume bottle on marble.")
    assert "orbits 90 degrees" in text and "Constraint: constant radius" in text
    assert ".." not in text and "\n" not in text
    assert "Sound:" not in text
    assert "Sound: rain on glass." in compile_prompt(CameraRig(), "A room", audio="rain on glass")


def test_still_prompt_describes_the_look_without_motion():
    text = rig.compile_still_prompt(CameraRig(movement="orbit_360"), "A glass bottle on marble.")
    assert text.startswith("A glass bottle on marble.") and "35mm" in text
    assert "orbit" not in text.lower() and "Constraint" not in text


def test_keyframed_shot_builds_first_last_segments():
    plan = compile_shot(CameraRig(movement="dolly_in", duration_seconds=5), "A lighthouse at dusk")
    assert [a.role for a in plan.anchors] == ["hero", "edit"]
    assert len(plan.segments) == 1
    seg = plan.segments[0]
    assert (seg.start_anchor, seg.end_anchor, seg.template, seg.seconds) == (0, 1, "ltx25_flf2v", 5)
    assert plan.total_seconds == 5 and not plan.notes


def test_full_orbit_returns_to_the_hero_frame_and_reports_the_duration_it_snaps_to():
    plan = compile_shot(CameraRig(movement="orbit_360", duration_seconds=5), "A bottle")
    assert [a.role for a in plan.anchors] == ["hero", "edit", "edit", "edit", "repeat_hero"]
    assert len(plan.segments) == 4
    assert plan.total_seconds == sum(s.seconds for s in plan.segments) == 8
    assert any("becomes 8s" in n for n in plan.notes)


def test_prompt_only_move_is_one_image_to_video_segment():
    plan = compile_shot(CameraRig(movement="handheld", duration_seconds=6), "A street at night")
    assert len(plan.anchors) == 1 and plan.segments[0].end_anchor is None
    assert plan.segments[0].template == "ltx25_i2v" and plan.total_seconds == 6


def test_quick_mode_turns_a_keyframed_move_into_one_still_and_a_camera_instruction():
    normal = compile_shot(CameraRig(movement="orbit_180", duration_seconds=6), "A bottle")
    quick = compile_shot(CameraRig(movement="orbit_180", duration_seconds=6), "A bottle", prompt_only=True)
    assert normal.mode == "keyframed" and len(normal.anchors) > 1
    assert quick.mode == "prompt_only" and [a.role for a in quick.anchors] == ["hero"]
    assert len(quick.segments) == 1 and quick.segments[0].template == "ltx25_i2v"
    assert quick.segments[0].seconds == quick.total_seconds == 6
    assert quick.prompt == normal.prompt, "the camera instruction is the same text either way"
    assert any("quick mode" in n for n in quick.notes)
    # a move that is already prompt-only is unchanged by the switch
    plain = compile_shot(CameraRig(movement="static"), "A bottle")
    assert compile_shot(CameraRig(movement="static"), "A bottle", prompt_only=True) == plain


def test_experimental_moves_are_flagged():
    plan = compile_shot(CameraRig(movement="vertigo"), "A hallway")
    assert any("experimental" in n for n in plan.notes)


@pytest.mark.parametrize(
    "bad",
    [
        {"sensor": "imax"}, {"lens": "fisheye"}, {"aperture": "f22"}, {"lighting": "disco"},
        {"speed": "warp"}, {"movement": "teleport"}, {"focal_length_mm": 4},
        {"focal_length_mm": 500}, {"duration_seconds": 1}, {"duration_seconds": 40},
    ],
)
def test_invalid_rigs_are_rejected(bad):
    with pytest.raises(ValueError):
        CameraRig(**bad).validate()


def test_the_javascript_fixtures_match_what_the_server_produces():
    """tests/js/*.test.mjs read snapshots of the catalog and plans; they must not go stale."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).parent / "js" / "make_fixtures.py"
    spec = importlib.util.spec_from_file_location("make_fixtures", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name, data in module.build().items():
        on_disk = (module.OUT / name).read_text(encoding="utf-8")
        if name == "recipe_link.json":  # compressed bytes may differ between zlib builds: check the round trip
            from openfield.engine import receipt as receipts

            stored = json.loads(on_disk)
            assert stored["recipe"] == data["recipe"]
            assert receipts.parse_recipe_link(stored["link"]) == data["recipe"]
            continue
        assert on_disk == module.render(data), f"{name} is stale: run python tests/js/make_fixtures.py"
