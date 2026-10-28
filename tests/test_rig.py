import json

import pytest

from openfield.engine import rig
from openfield.engine.rig import EFFECTS, CameraRig, catalog, compile_prompt, compile_shot


def test_exactly_49_unique_moves_in_known_groups():
    assert len(rig.MOVES) == 49
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
        needed = move.anchors - 2 if move.id in rig.RETURNS else move.anchors - 1  # a move that ends on its hero needs no last edit
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
    assert len(data["moves"]) == 49
    assert data["moves"][0]["path"] and "group_label" in data["moves"][0]
    assert "anamorphic" in data["options"]["lens"]


@pytest.fixture
def style1(monkeypatch):
    """These tests describe style 1's words (the Constraint line, the look sentence, the Sound label)."""
    monkeypatch.setenv("OPENFIELD_PROMPT_STYLE", "1")


def test_prompt_is_one_clean_paragraph_with_the_constraint(style1):
    text = compile_prompt(CameraRig(movement="orbit_90"), "A glass perfume bottle on marble.")
    assert text.startswith("A glass perfume bottle on marble.")
    assert "orbits 90 degrees" in text and "Constraint: constant radius" in text
    assert ".." not in text and "\n" not in text
    assert "Sound:" not in text
    assert "Sound: rain on glass." in compile_prompt(CameraRig(), "A room", audio="rain on glass")


def test_an_effect_preset_adds_one_sentence_to_the_shot_prompt_and_nothing_else(style1):
    plain = compile_prompt(CameraRig(), "A room")
    rainy = compile_prompt(CameraRig(effect="rain"), "A room")
    assert plain == compile_prompt(CameraRig(effect="none"), "A room"), "none is the same as no effect"
    assert "Heavy rain falls across the whole frame" in rainy and rainy.startswith("A room.")
    assert rainy.index("Heavy rain") < rainy.index("Constraint:"), "the effect sits with the scene, before the camera constraint"
    assert rainy.replace(f"{EFFECTS['rain']} ", "") == plain
    with pytest.raises(ValueError, match="unsupported effect"):
        compile_prompt(CameraRig(effect="snow"), "A room")
    assert "effect" in catalog()["options"] and "fog" in catalog()["options"]["effect"]
    assert catalog()["defaults"]["effect"] == "none" and isinstance(catalog()["effects_tested"], list)


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
    plan = compile_shot(CameraRig(movement="orbit_360", duration_seconds=5), "A bottle", single_pass=False)  # the segmented path
    assert [a.role for a in plan.anchors] == ["hero", "edit", "edit", "edit", "repeat_hero"]
    assert len(plan.segments) == 4
    assert plan.total_seconds == sum(s.seconds for s in plan.segments) == 8
    assert any("becomes 8s" in n for n in plan.notes)


def test_prompt_only_move_is_one_image_to_video_segment():
    plan = compile_shot(CameraRig(movement="handheld", duration_seconds=6), "A street at night")
    assert len(plan.anchors) == 1 and plan.segments[0].end_anchor is None
    assert plan.segments[0].template == "ltx25_i2v" and plan.total_seconds == 6


def test_quick_mode_turns_a_keyframed_move_into_one_still_and_a_camera_instruction():
    normal = compile_shot(CameraRig(movement="orbit_360", duration_seconds=6), "A bottle")
    quick = compile_shot(CameraRig(movement="orbit_360", duration_seconds=6), "A bottle", prompt_only=True)
    assert normal.mode == "keyframed" and len(normal.anchors) > 1
    assert quick.mode == "prompt_only" and [a.role for a in quick.anchors] == ["hero"]
    assert len(quick.segments) == 1 and quick.segments[0].template == "ltx25_i2v"
    assert quick.segments[0].seconds == quick.total_seconds == 6
    assert quick.prompt == normal.prompt, "the camera instruction is the same text either way"
    assert any(n.startswith("quick mode: one still") for n in quick.notes)
    # a move that is already prompt-only is unchanged by the switch
    plain = compile_shot(CameraRig(movement="static"), "A bottle")
    assert compile_shot(CameraRig(movement="static"), "A bottle", prompt_only=True) == plain


def test_no_plan_note_talks_about_testing():
    # round 11: the interface does not print tested or untested; the server's flags still decide what plays at rest
    for move_id in ("rack_focus", "vertigo", "helicopter"):
        plan = compile_shot(CameraRig(movement=move_id, angle="back/high/wide"), "A hallway", line="Hello there")
        assert not any("tested" in n or "validated" in n for n in plan.notes), (move_id, plan.notes)


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


def test_a_transformation_edits_the_last_still_and_renders_first_to_last():
    plan = compile_shot(CameraRig(movement="static", effect="ignite"), "A cabin")
    assert [a.role for a in plan.anchors] == ["hero", "transform"] and plan.anchors[1].check_identity
    assert plan.segments[0].template == "ltx25_flf2v" and plan.segments[0].end_anchor == 1
    assert plan.transformation == "ignite" and "Flames catch" in plan.prompt
    gold = compile_shot(CameraRig(movement="dolly_in", effect="gold"), "A cabin")
    assert [a.role for a in gold.anchors] == ["hero", "transform"] and gold.anchors[1].check_identity is False
    assert gold.anchors[1].edit_prompt.endswith(rig.TRANSFORMATIONS["gold"].edit) and "much closer" in gold.anchors[1].edit_prompt
    orbit = compile_shot(CameraRig(movement="orbit_360", effect="freeze"), "A bottle")
    assert "repeat_hero" not in [a.role for a in orbit.anchors] and orbit.anchors[-1].role == "transform"
    quick = compile_shot(CameraRig(movement="orbit_180", effect="bloom"), "A bottle", prompt_only=True)
    assert [a.role for a in quick.anchors] == ["hero", "transform"] and len(quick.segments) == 1
    assert compile_shot(CameraRig(movement="static"), "A cabin").transformation is None
    assert "snow" not in rig.EFFECT_IDS and "snowfall" in catalog()["options"]["effect"]
    kinds = {e["id"]: e["kind"] for e in catalog()["effects"]}
    assert kinds["rain"] == "prompt" and kinds["gold"] == "keyframed" and kinds["none"] == "prompt"


def test_a_grade_is_one_phrase_in_both_look_sentences_and_absent_by_default():
    plain = compile_prompt(CameraRig(), "A room")
    graded = compile_prompt(CameraRig(grade="kodachrome"), "A room")
    assert "Kodachrome" in graded and "Kodachrome" not in plain
    assert "Kodachrome" in rig.compile_still_prompt(CameraRig(grade="kodachrome"), "A room")
    assert catalog()["defaults"]["grade"] == "none" and "kodachrome" in catalog()["options"]["grade"]
    with pytest.raises(ValueError, match="unsupported grade"):
        CameraRig(grade="sepia").validate()


def test_score_and_soundscape_are_sound_prompt_words_and_absent_by_default(style1):
    plain = compile_prompt(CameraRig(), "A room")
    scored = compile_prompt(CameraRig(score="strings", soundscape="harbour"), "A room")
    assert scored.endswith(
        "Sound: waves against a pier, gulls, rigging in the wind. "
        "Music: a slow string swell, continuing across the whole shot."
    )
    assert "Sound:" not in plain
    assert "sound" not in plain.lower()  # the prompt is otherwise silent
    assert catalog()["defaults"]["score"] == "none" and catalog()["defaults"]["soundscape"] == "none"
    assert "solo_piano" in catalog()["options"]["score"] and "city_night" in catalog()["options"]["soundscape"]
    with pytest.raises(ValueError, match="unsupported score"):
        CameraRig(score="orchestra").validate()
    with pytest.raises(ValueError, match="unsupported soundscape"):
        CameraRig(soundscape="space_station").validate()
    no_music = compile_prompt(CameraRig(score="no_music"), "A room")
    assert no_music.endswith("No music.")


def test_one_pass_guides_the_middle_stills_at_their_frames():
    full = compile_shot(CameraRig(movement="orbit_360", duration_seconds=5), "A bottle", single_pass=True)
    assert len(full.segments) == 1 and full.segments[0].mids == ((1, 32), (2, 64), (3, 88)) and full.total_seconds == 5
    assert (full.segments[0].end_anchor, full.segments[0].seconds, full.segments[0].template) == (4, 5, "ltx25_flf2v")
    assert any("one pass" in n for n in full.notes) and not any("becomes" in n for n in full.notes)
    assert rig.mid_frame_index(1, 3, 5) == 64, "a three-still move guides its middle still at the middle frame"
    short = compile_shot(CameraRig(movement="orbit_360", duration_seconds=2), "A bottle", single_pass=True)
    frames = [f for _, f in short.segments[0].mids]
    assert frames == sorted(set(frames)) and all(8 <= f <= 2 * rig.LTX_FPS + 1 - 1 - 8 for f in frames)
    two = compile_shot(CameraRig(movement="dolly_in"), "A bottle", single_pass=True)
    assert len(two.segments) == 1 and two.segments[0].mids == ()
    segmented = compile_shot(CameraRig(movement="orbit_360", duration_seconds=4), "A bottle", single_pass=False)
    assert len(segmented.segments) == 4 and not segmented.segments[0].mids
    assert rig.SINGLE_PASS is True and rig.MID_GUIDE_STRENGTH == 0.4, "on since the Oct 22 sweep found 0.4 clean"
    with pytest.raises(ValueError):
        rig.mid_frame_index(0, 3, 5)


def test_the_ltx_frame_rate_matches_the_template():
    from openfield.engine.workflows import load_template

    graph = load_template("ltx25_flf2v").graph
    assert graph["251:205"]["inputs"]["value"] == rig.LTX_FPS


def test_an_angle_re_shoots_the_hero_and_the_default_adds_nothing():
    assert compile_shot(CameraRig(), "A cabin").angle is None
    plan = compile_shot(CameraRig(angle="back_left/low/wide"), "A cabin")
    assert plan.angle["label"] == "Back-left quarter · Low angle · Wide" and plan.angle["azimuth_deg"] == 225
    assert compile_shot(CameraRig(angle="back_left/eye/medium"), "A cabin").angle["tested"] is True, "on the Oct 22 sheet"
    assert plan.angle["elevation_deg"] == -30 and plan.angle["distance"] == 1.8 and plan.angle["tested"] is True, "checked on its still, Oct 25"
    assert compile_shot(CameraRig(angle="front_left/low/wide"), "A cabin").angle["tested"] is False,         "a front quarter whose still kept him facing the lens (Oct 25)"
    assert "back-left quarter view" in plan.angle["directive"] and "低角度" in plan.angle["directive"]
    assert "Move only the camera" in plan.angle["directive"] and any("angled" in n for n in plan.notes)
    assert "将" not in rig.angle_directive("front/eye/medium"), "the default has no rotation to ask for in Chinese"
    for bad in ("front", "front/eye", "up/eye/medium", "front/eye/far", "front-eye-medium"):
        with pytest.raises(ValueError, match="unsupported angle"):
            CameraRig(angle=bad).validate()
    cat = catalog()["angles"]
    assert [a["id"] for a in cat["azimuths"]][:2] == ["front", "front_right"] and cat["default"] == "front/eye/medium"
    assert len(cat["tested"]) == 65 and "front/eye/wide" in cat["tested"] and catalog()["defaults"]["angle"] == "front/eye/medium"
    assert rig.describe_angle("right/high/close") == "Right side · High angle · Close-up"


def test_the_signature_moves_are_prompt_only_with_their_tempo_in_the_phrase():
    new = ["crash_zoom_in", "crash_zoom_out", "eyes_in", "snorricam", "through_object", "hyperlapse", "lazy_susan"]
    for move_id in new:
        move = rig.MOVES[move_id]
        assert move.mode == "prompt_only" and move.anchors == 1 and not move.edits, move_id
        assert move.featured == (move_id == "crash_zoom_in"), "crash zoom in is promoted since Oct 25"
        assert all(abs(v) < 10 for p in move.path() for v in (p.x, p.y, p.z)), "a finite path for the stage"
    assert {"crash_zoom_in", "snorricam", "hyperlapse", "lazy_susan", "eyes_in"} <= rig.VALIDATED, "five of the six that held their Oct 22 render"
    assert "through_object" in rig.VALIDATED, "Oct 26: made as its reverse (a dolly out played backwards): r13-c-through-hut-1341 held"
    assert "crash_zoom_out" in rig.VALIDATED, "Oct 24, style 2: snaps wide and holds (on Oct 22 the subject left the frame)"
    assert "vertigo" in rig.VALIDATED, "Oct 26: the face-tracked window held the subject at her size (r13-c-vertigo-corridor-1361)"
    assert "moving" not in compile_prompt(CameraRig(movement="crash_zoom_in"), "A face")
    assert "moving slowly" in compile_prompt(CameraRig(movement="eyes_in", speed="slow"), "A face")
    assert rig.MOVES["vertigo"].label == "Dolly zoom (vertigo)" and rig.MOVES["top_down"].label == "Overhead"
    assert [m.id for m in rig.MOVES.values() if m.featured] == [m.id for m in rig.MOVES.values() if m.featured][:12]


NEW_MOVES = ["bullet_time", "aerial_pullback", "dutch_angle", "fisheye", "super_dolly_in", "yoyo_zoom"]
NEW_EFFECTS = ["bts", "vanish", "clones", "comic", "painting", "melt", "flood"]


def test_the_new_signature_moves_are_prompt_only_with_one_anchor_and_no_render_of_their_own():
    assert list(rig.MOVES)[-6:] == NEW_MOVES, "the six sit at the end of the table"
    for move_id in NEW_MOVES:
        move = rig.MOVES[move_id]
        assert all(abs(v) < 10 for p in move.path() for v in (p.x, p.y, p.z)), "a finite path for the stage"
        assert move.featured == (move_id == "bullet_time"), "bullet time is promoted since it held (Oct 25)"
        assert move.mode == "prompt_only" and move.anchors == 1 and not move.edits, move_id
        if move_id == "bullet_time":  # made from the orbit and the time freeze since Oct 25 (see the next test)
            continue
        # Oct 24: the super dolly in held (cast-free, style 2); the Dutch angle held once it was turned in code (Oct 25)
        assert move.id in rig.VALIDATED, move_id
    # two of them carry their tempo in the phrase, so the shot prompt adds no speed to them
    for move_id in ("yoyo_zoom", "aerial_pullback"):
        assert "moving" not in compile_prompt(CameraRig(movement=move_id), "A face"), move_id


# The prompt of the session-9 take that held as bullet time (r11-bt4-samurai-90, tk_20261025_141822_44ee): the camera
# circled Tomas, frozen mid-strike, from the front to behind his shoulder. An orbit 90 with the time-freeze effect, style 2.
SAMURAI_TAKE = (
    "Tomas in black samurai armour, katana raised mid-strike, sparks and raindrops frozen in the air around the blade, on a "
    "neon-lit Tokyo street at night. The camera orbits 90 degrees around the subject at constant distance, the subject "
    "staying centred while the background rotates behind it, moving at a steady pace. The camera circles a quarter turn "
    "at the same distance and height and ends with the subject seen from the side, still centred. The world slows and "
    "freezes mid-motion while the camera keeps moving. Shot on a clean modern digital cinema camera with a clean, sharp "
    "spherical lens, 35mm (natural), at f/4 with moderate depth of field; practical lights in the scene making warm pools "
    "of light. We hear a deep slowed-down whoosh, then the hush of frozen rain.")
# The October 23 time-freeze take (tk_20261023_091155_5b5b), the same parts in prompt style 1.
TIME_FREEZE_TAKE = (
    "Mara throws a glass of water into the air on a beach at sunset. Shot on a clean modern digital cinema camera with a "
    "clean, sharp spherical lens, 35mm (natural), at f/4 with moderate depth of field; soft cross lighting that sculpts "
    "the subject. The camera orbits 90 degrees around the subject at constant distance, the subject staying centred "
    "while the background rotates behind it, moving at a steady pace. The world slows and freezes mid-motion while the "
    "camera keeps moving. Constraint: constant radius, constant height, subject remains centred, no subject spin.")


def test_bullet_time_is_made_from_the_orbit_and_the_time_freeze_that_held():
    """Oct 25 (GPU session 9): asked for in words, LTX played the dancer out and held the camera still; re-shot from the
    side by the angle edits, the subjects only turned their heads; the Oct 23 style-1 prompt rolled, pulled back or held
    still. The style-2 orbit 90 with the time-freeze sentence circled Tomas frozen mid-strike: bullet time is that."""
    move = rig.MOVES["bullet_time"]
    assert move.mode == "prompt_only" and move.anchors == 1 and not move.edits and move.describe()["frozen"]
    assert abs(move.path()[-1].yaw + 90) < 1e-6, "a quarter circle on the stage, ending at the side"
    look = dict(sensor="modern_digital", lens="clean_sharp", focal_length_mm=35, aperture="f4", lighting="practicals", speed="steady")
    subject = ("Tomas in black samurai armour, katana raised mid-strike, sparks and raindrops frozen in the air around the "
               "blade, on a neon-lit Tokyo street at night")
    audio = "a deep slowed-down whoosh, then the hush of frozen rain"
    assert compile_prompt(CameraRig(movement="bullet_time", **look), subject, audio) == SAMURAI_TAKE
    assert compile_prompt(CameraRig(movement="bullet_time", effect="time_freeze", **look), subject, audio) == SAMURAI_TAKE, "said once"
    assert compile_prompt(CameraRig(movement="orbit_90", effect="time_freeze", **look), subject, audio) == SAMURAI_TAKE, \
        "the take was rendered as an orbit 90 with the effect: bullet time sends the same words"
    mara = dict(look, lighting="soft_cross")
    assert compile_prompt(CameraRig(movement="bullet_time", **mara), "Mara throws a glass of water into the air on a beach "
                          "at sunset", style=1) == TIME_FREEZE_TAKE, "style 1 keeps the October 23 words"
    plan = compile_shot(CameraRig(movement="bullet_time"), "A dancer mid-leap through a wall of water", action="she bursts through the spray")
    assert plan.mode == "prompt_only" and [a.role for a in plan.anchors] == ["hero"]
    assert [s.template for s in plan.segments] == ["ltx25_i2v"]
    assert "bursts" not in plan.prompt and rig.EFFECTS["time_freeze"] in plan.prompt, "the action stays out of the video prompt"
    assert "made as an orbit 90 around one still of the moment at its peak, with the world frozen while the camera moves" in plan.notes
    quick = compile_shot(CameraRig(movement="bullet_time"), "A dancer", prompt_only=True)
    assert quick.to_dict() == compile_shot(CameraRig(movement="bullet_time"), "A dancer").to_dict(), "quick mode changes nothing"
    still = rig.compile_still_prompt(CameraRig(movement="bullet_time"), "A dancer mid-leap", action="she bursts through the spray")
    assert "She bursts through the spray." in still and rig.HERO_MOMENT["bullet_time"] in still
    assert rig.HERO_MOMENT["bullet_time"] not in rig.compile_still_prompt(CameraRig(movement="dolly_in"), "A dancer", action="she spins")
    with pytest.raises(ValueError, match="camera as shot"):
        compile_shot(CameraRig(movement="bullet_time", angle="back/eye/medium"), "A dancer mid-leap")


def test_the_new_transformations_are_keyframed_effects_that_reframe_only_when_they_say_so():
    for effect_id in NEW_EFFECTS:
        assert effect_id in rig.TRANSFORMATIONS and effect_id in rig.EFFECT_IDS, effect_id
        assert effect_id in rig.VALIDATED_EFFECTS, f"{effect_id}: all seven held on the Oct 23 renders (v2-fx-*)"
    assert rig.TRANSFORMATIONS["bts"].reframes is True
    assert all(t.reframes is False for k, t in rig.TRANSFORMATIONS.items() if k != "bts")
    assert rig.TRANSFORMATIONS["bts"].keeps_identity is True
    assert rig.TRANSFORMATIONS["vanish"].keeps_identity is False
    assert rig.TRANSFORMATIONS["melt"].keeps_identity is True
    assert rig.TRANSFORMATIONS["flood"].keeps_identity is True
    assert "snow" not in rig.EFFECT_IDS
    plan = compile_shot(CameraRig(movement="static", effect="vanish"), "A cabin")
    assert [a.role for a in plan.anchors] == ["hero", "transform"]
    assert plan.anchors[1].check_identity is False
    assert plan.transformation == "vanish"


def test_a_spoken_line_is_quoted_with_its_delivery_and_language_and_stays_out_of_silent_recipes(style1):
    from openfield.engine import rig as rig_module
    text = compile_prompt(CameraRig(), "Mara at the pier", "waves", line=' "We leave at first light." ', delivery="calm", language="English")
    assert 'in English, in a calm, low voice, unhurried, lips moving with the words: "We leave at first light." Sound: waves.' in text
    assert "Sound:" in text and text.index("speaks") < text.index("Sound:"), "the line comes before the sound bed"
    plain = compile_prompt(CameraRig(), "Mara at the pier", line="Come home.")
    assert 'speaks in a natural speaking voice, lips moving with the words: "Come home."' in plain and "in English" not in plain
    plan = compile_shot(CameraRig(movement="static"), "Mara at the pier", line="Come home.", delivery="whisper")
    assert plan.dialogue == {"line": "Come home.", "delivery": "whisper", "tested": rig_module.DIALOGUE_TESTED}
    assert plan.notes[-1].startswith("dialogue: LTX 2.5 speaks the line")
    assert compile_shot(CameraRig(), "A lighthouse").dialogue is None
    for bad in ({"line": "x" * 201}, {"line": "hi", "delivery": "sing"}, {"line": "hi", "language": "y" * 41}):
        with pytest.raises(ValueError):
            compile_shot(CameraRig(), "A lighthouse", **bad)
    assert compile_shot(CameraRig(), "A lighthouse", line="   ").dialogue is None, "a blank line is silence, not an error"
    cat = catalog()["dialogue"]
    assert [d["id"] for d in cat["deliveries"]] == list(rig_module.DELIVERIES) and cat["tested"] is rig_module.DIALOGUE_TESTED
    assert cat["max_chars"] == rig_module.LINE_MAX


def test_an_action_is_its_own_sentence_after_the_subject_in_the_shot_prompt_and_never_in_the_still(style1):
    subject = "A samurai in a bamboo grove, his hand on the hilt of his katana"
    action = "He draws the katana in one swift motion and holds it high"
    cam = CameraRig(movement="static")
    plan = compile_shot(cam, subject, "steel ringing", action=f"  {action} \n")
    assert plan.prompt.startswith(f"{subject}. {action}. Shot on "), "what happens comes right after what is there"
    assert plan.action == action, "the words are kept with the whitespace collapsed"
    assert action not in rig.compile_still_prompt(cam, subject), "the hero still shows the moment before the action"
    assert compile_prompt(cam, subject, action="he looks up,").startswith(f"{subject}. He looks up. Shot on ")
    for blank in (None, "", "   "):
        assert compile_shot(cam, subject, action=blank).prompt == compile_prompt(cam, subject), "no action, no change"
        assert compile_shot(cam, subject, action=blank).action is None
    assert len(compile_shot(cam, subject, action="x " * 150).action) == 299, "whitespace is collapsed before counting"
    assert compile_shot(cam, subject, action="y" * rig.ACTION_MAX).action == "y" * rig.ACTION_MAX
    for bad in ("ab", " a ", "x" * (rig.ACTION_MAX + 1), "He takes off his shirt", 42):
        with pytest.raises(ValueError):
            compile_shot(cam, subject, action=bad)
    assert catalog()["action_max"] == rig.ACTION_MAX == 300


def test_an_action_on_a_keyframed_move_is_noted_and_the_mode_is_left_alone():
    note = ("action: a keyframed move pins its first and last stills to the same moment, so the action may barely "
            "move; quick mode or a one-still move gives it room")
    action = "He draws the katana"
    keyframed = compile_shot(CameraRig(movement="dolly_in"), "A samurai", action=action)
    assert keyframed.mode == "keyframed" and note in keyframed.notes
    quick = compile_shot(CameraRig(movement="dolly_in"), "A samurai", action=action, prompt_only=True)
    assert quick.mode == "prompt_only" and note not in quick.notes
    assert note not in compile_shot(CameraRig(movement="dolly_in"), "A samurai").notes
    assert note not in compile_shot(CameraRig(movement="static"), "A samurai", action=action).notes


def test_a_transition_prompt_names_the_style_and_both_shots_and_is_bounded():
    text = rig.compile_transition_prompt("push", "Mara on the pier", "Oskar at the net")
    assert text.startswith(rig.TRANSITIONS["push"].phrase)
    assert "first shot: Mara on the pier." in text and "second shot: Oskar at the net." in text
    long = rig.compile_transition_prompt("morph", "x" * 1000, "")
    assert "x" * rig.TRANSITION_SCENE_MAX in long and "x" * (rig.TRANSITION_SCENE_MAX + 1) not in long
    assert "second shot: the scene." in long
    with pytest.raises(ValueError):
        rig.compile_transition_prompt("spin", "a", "b")
    assert rig.TRANSITIONS_TESTED <= set(rig.TRANSITIONS)


def test_an_extend_prompt_continues_the_shot_and_keeps_the_text_bounded():
    text = rig.compile_extend_prompt("Mara on the pier at golden hour")
    assert text.startswith("The same shot continues without a cut from where it ended:")
    assert "Mara on the pier at golden hour" in text
    long = rig.compile_extend_prompt("x" * 2000)
    assert "x" * rig.EXTEND_PROMPT_MAX in long and "x" * (rig.EXTEND_PROMPT_MAX + 1) not in long
    empty = rig.compile_extend_prompt("   ")
    assert empty.endswith("the scene.")
    cat = rig.catalog()["extend"]
    assert cat["seconds"] == list(rig.EXTEND_SECONDS) and cat["tested"] is rig.EXTEND_TESTED


def test_an_edit_prompt_carries_the_words_or_a_light_and_refuses_what_it_cannot_do():
    assert rig.compile_edit_prompt("remove", "the fishing net").startswith("Remove the fishing net from the picture")
    assert rig.LIGHTS["neon"] in rig.compile_edit_prompt("relight", "neon")
    assert rig.compile_edit_prompt("face_swap") == rig.FACE_SWAP
    for preset, detail in (("remove", ""), ("outfit", None), ("custom", "x" * (rig.EDIT_DETAIL_MAX + 1)), ("blur", "a")):
        with pytest.raises(ValueError):
            rig.compile_edit_prompt(preset, detail)
    assert {p["id"] for p in catalog()["edits"]["presets"] if p["needs_cast"]} == {"face_swap", "character_swap"}
    assert rig.EDITS_TESTED == frozenset(rig.EDITS), "every preset was rendered and checked on Oct 23"
    assert "slow_motion" in rig.VALIDATED_EFFECTS, "checked by eye on Oct 23 (v2-fx-slow-motion)"


def test_the_seamless_loop_ends_on_its_own_first_still():
    plan = compile_shot(CameraRig(movement="loop"), "Waves rolling onto a black sand beach")
    assert [a.role for a in plan.anchors] == ["hero", "repeat_hero"]
    assert [(s.start_anchor, s.end_anchor, s.template) for s in plan.segments] == [(0, 1, "ltx25_flf2v")]
    assert "loop" in rig.VALIDATED, "two loops (storm waves, campfire) closed on the Oct 23 renders"


def test_an_edit_never_undresses_or_dresses_a_person_in_underwear():
    for preset, detail in (("remove", "her clothes"), ("outfit", "nothing"), ("outfit", "see-through underwear"),
                           ("custom", "take off his shirt and trousers"), ("remove", "her bikini top"),
                           ("outfit", "a bikini"), ("custom", "put her in lingerie")):
        with pytest.raises(ValueError):
            rig.compile_edit_prompt(preset, detail)
    # swimwear by other names, a towel, latex, and clothes made wet or see-through
    for preset, detail in (("outfit", "a bathing suit"), ("outfit", "swim trunks"), ("outfit", "a speedo"),
                           ("outfit", "only a towel"), ("outfit", "a white bath towel"), ("outfit", "a skin-tight latex bodysuit"),
                           ("custom", "make her clothes wet and clinging"), ("custom", "make her shirt transparent"),
                           ("outfit", "a sheer blouse")):
        with pytest.raises(ValueError, match="never puts a person in underwear"):
            rig.compile_edit_prompt(preset, detail)
    assert rig.compile_edit_prompt("outfit", "a red wool coat").startswith("Dress the person in a red wool coat")
    assert rig.compile_edit_prompt("remove", "the hat").startswith("Remove the hat")
    # sheer and transparent are refused only when said of a garment
    assert rig.compile_edit_prompt("remove", "the transparent plastic bag").startswith("Remove the transparent plastic bag")
    assert "sheer curtains" in rig.compile_edit_prompt("relight", "soft light through sheer curtains")
    assert rig.compile_edit_prompt("custom", "make the window glass transparent").startswith("make the window glass transparent")
    assert rig.compile_edit_prompt("outfit", "a lab coat and latex gloves")
    assert rig.dresses_down(None, "", "A woman on a pier") is False and rig.dresses_down("me in a bikini") is True


def test_moves_with_their_own_tempo_get_no_speed_words_and_a_lens_move_names_one_lens():
    steady = f"moving {rig.SPEEDS[rig.CameraRig().speed]}"
    for move in ("loop", "dutch_angle"):
        assert steady not in rig.compile_prompt(rig.CameraRig(movement=move), "A lighthouse at dusk"), move
    fish = rig.CameraRig(movement="fisheye")
    for text in (rig.compile_prompt(fish, "A skater in a bowl"), rig.compile_still_prompt(fish, "A skater in a bowl")):
        assert "fisheye lens" in text and "mm (" not in text, "the still and the shot name the same single lens"
    assert "mm (" in rig.compile_still_prompt(rig.CameraRig(), "A skater in a bowl")


def test_a_loop_says_when_quick_mode_or_a_transformation_breaks_it():
    quick = rig.compile_shot(rig.CameraRig(movement="loop"), "Waves on a black beach", prompt_only=True)
    assert any("may not end where it began" in n for n in quick.notes)
    fx = rig.compile_shot(rig.CameraRig(movement="loop", effect="freeze"), "Waves on a black beach")
    assert any("no longer flows back" in n for n in fx.notes) and not any("full orbit" in n for n in fx.notes)
    orbit = rig.compile_shot(rig.CameraRig(movement="orbit_360", effect="freeze"), "A thermos on a table")
    assert any("full orbit" in n for n in orbit.notes)


def test_the_upscale_catalog_names_its_targets_and_says_it_is_tested():
    assert rig.UPSCALE_TARGETS == {"2k": 2560, "4k": 3840} and all(side % 2 == 0 for side in rig.UPSCALE_TARGETS.values())
    assert rig.UPSCALE_MODEL_SCALE == 4 and rig.UPSCALE_TESTED is True
    assert catalog()["upscale"] == {
        "targets": [{"id": "2k", "label": "2K", "long_side": 2560}, {"id": "4k", "label": "4K", "long_side": 3840}],
        "tested": True}  # the Draft-to-2K upscale of Oct 23 holds by eye


def test_a_one_still_shot_frames_its_first_still_for_the_move():
    assert set(rig.START_FRAMING) <= set(rig.MOVES), "every framing names a real move"
    zoom_in = rig.compile_still_prompt(rig.CameraRig(movement="crash_zoom_in"), "A cat DJ on a neon stage")
    assert "Framed as a wide shot" in zoom_in and zoom_in.startswith("A cat DJ on a neon stage. Framed")
    assert "tight close-up" in rig.compile_still_prompt(rig.CameraRig(movement="crash_zoom_out"), "A cat DJ")
    # a keyframed dolly in gets its framing from its anchors; in quick mode its one still starts wide
    keyframed = rig.CameraRig(movement="dolly_in")
    assert "Framed" not in rig.compile_still_prompt(keyframed, "A cat DJ")
    assert "Framed as a wide shot" in rig.compile_still_prompt(keyframed, "A cat DJ", one_still=True)
    assert "Framed" not in rig.compile_still_prompt(rig.CameraRig(), "A cat DJ"), "a static shot is framed as written"


def test_a_transition_idea_goes_into_the_bridge_prompt_only_when_given():
    plain = rig.compile_transition_prompt("push", "a dragon over a city", "a surfer on a lava wave")
    assert "How it gets there" not in plain
    idea = rig.compile_transition_prompt("push", "a dragon over a city", "a surfer on a lava wave",
                                         "  the camera flies into the dragon's fire and comes out of a lava wave. ")
    assert "How it gets there: the camera flies into the dragon's fire and comes out of a lava wave. It starts" in idea
    assert rig.transition_idea("   ") is None
    with pytest.raises(ValueError):
        rig.transition_idea("x" * (rig.TRANSITION_IDEA_MAX + 1))


def test_prompt_style_2_ends_each_move_in_positive_words_and_drops_the_default_look(monkeypatch):
    monkeypatch.delenv("OPENFIELD_PROMPT_STYLE", raising=False)
    assert rig.prompt_style() == 2  # the default since October 24
    default = rig.CameraRig(movement="dolly_in")
    one = rig.compile_prompt(default, "A lighthouse at dusk", "waves on rocks", style=1)
    two = rig.compile_prompt(default, "A lighthouse at dusk", "waves on rocks")
    assert "Constraint:" in one and "Shot on" in one and "Sound:" in one
    assert "Constraint:" not in two and "Shot on" not in two and "Sound:" not in two
    assert rig.ENDS["dolly_in"] in two and "We hear waves on rocks." in two
    graded = rig.compile_prompt(rig.CameraRig(movement="dolly_in", grade="noir_mono"), "A lighthouse at dusk", style=2)
    assert "Shot on" in graded  # a look the person chose is kept
    monkeypatch.setenv("OPENFIELD_PROMPT_STYLE", "1")
    assert rig.compile_prompt(default, "A lighthouse at dusk", "waves on rocks") == one
    monkeypatch.setenv("OPENFIELD_PROMPT_STYLE", "banana")
    assert rig.prompt_style() == 2


def test_style_2_keeps_the_effect_with_the_scene_and_the_line_before_the_sound(monkeypatch):
    monkeypatch.delenv("OPENFIELD_PROMPT_STYLE", raising=False)
    rainy = compile_prompt(CameraRig(effect="rain"), "A room")
    assert rainy.startswith("A room.") and "Heavy rain falls across the whole frame" in rainy
    assert rainy.index(rig.ENDS["dolly_in"]) < rainy.index("Heavy rain"), "the camera, then the weather"
    talk = compile_prompt(CameraRig(movement="static"), "Mara at the pier", "waves", line="Come home.", delivery="calm")
    assert talk.index("speaks") < talk.index("We hear waves."), "the line comes before the sound bed"
    scored = compile_prompt(CameraRig(score="strings", soundscape="harbour"), "A room")
    assert scored.endswith("We hear waves against a pier, gulls, rigging in the wind. "
                           "The music is a slow string swell, continuing across the whole shot.")
    assert compile_prompt(CameraRig(score="no_music"), "A room").endswith("No music.")


def test_every_move_has_a_style_2_end_state_without_negations():
    import re
    negation = re.compile(r"\b(no|never|not|without|zero)\b", re.I)
    for move in rig.catalog()["moves"]:
        end = rig.ENDS[move["id"]]
        assert end and not negation.search(end), move["id"]
        phrase = rig.PHRASES_V2.get(move["id"], move["phrase"])
        assert not negation.search(phrase), move["id"]


def test_the_dutch_angle_is_shot_level_and_turned_in_code_afterwards():
    plan = compile_shot(CameraRig(movement="dutch_angle"), "A detective in a rain-soaked alley")
    assert plan.roll == 15.0 and plan.to_dict()["roll"] == 15.0
    assert any(n.startswith("rolled: the shot is rendered level (larger where the template allows), then the video is turned 15 degrees")
               for n in plan.notes)
    assert plan.segments[0].template == "ltx25_i2v" and len(plan.anchors) == 1, "one still, shot static"
    static = compile_prompt(CameraRig(movement="static"), "A detective in a rain-soaked alley")
    assert plan.prompt == static, "LTX is asked for a level, static shot; the turn is made afterwards"
    hero = rig.compile_still_prompt(CameraRig(movement="dutch_angle"), "A detective")
    assert "wide shot" in hero and "room above the head" in hero and "degrees" not in hero and "rolled" not in hero,         "the still is drawn level and wide: the turn crops it to a medium shot"
    assert set(rig.ROLLS) <= set(rig.MOVES)
    assert all(compile_shot(CameraRig(movement=m), "A detective").roll is None for m in ("static", "dolly_in", "orbit_360"))


def test_mirrored_moves_render_their_tested_twin_and_the_dolly_zoom_is_a_zoomed_dolly_out():
    """Oct 25: track left and truck left went the wrong way or barely moved; their twins held. So each is made from its
    twin's render on the flipped hero, flipped back (arc right was made from arc left this way until both arcs became
    two stills on Oct 26). The dolly zoom came out a plain pull-out in words; now it is a dolly-out zoomed in code,
    following the face."""
    assert rig.MIRRORS == {"track_left": "track_right", "truck_left": "truck_right"}
    assert not {"arc_left", "arc_right"} & rig.VALIDATED, "Oct 25: measured, arc left's takes stood still or arced right"
    for move_id, twin in rig.MIRRORS.items():
        assert move_id not in rig.VALIDATED or twin in rig.VALIDATED, f"{move_id} is flagged only if its twin held"
        plan = compile_shot(CameraRig(movement=move_id), "A lighthouse at dusk")
        assert plan.mirror == twin and plan.reframe is None and plan.move_id == move_id
        assert plan.prompt == compile_shot(CameraRig(movement=twin), "A lighthouse at dusk").prompt, "LTX gets the twin's words"
        assert any(note.startswith("mirrored:") for note in plan.notes)
    vertigo = compile_shot(CameraRig(movement="vertigo"), "A lighthouse at dusk")
    assert vertigo.mode == "keyframed" and [a.role for a in vertigo.anchors] == ["hero", "edit"]
    assert vertigo.reframe["zoom"] == (1.0, 1.8) and vertigo.mirror is None
    assert vertigo.anchors[1].edit_prompt == rig.MOVES["dolly_out"].edits[0], "its end still is the dolly-out's"
    assert "dollies out" in vertigo.prompt, "LTX renders a dolly-out; the zoom is made afterwards"
    assert "vertigo" in rig.MOVES["vertigo"].phrase or "dolly-zoom" in rig.MOVES["vertigo"].phrase, "the interface still says what it is"
    assert rig.TRACKED == {"vertigo": "face"} and vertigo.reframe["track"] == "face", "Oct 26: the zoom follows the face"
    assert any("the zoom follows the face it finds in the render, or runs 1x to 1.8x" in n for n in vertigo.notes)
    for move_id in set(rig.REFRAMES) - set(rig.TRACKED):
        assert "track" not in compile_shot(CameraRig(movement=move_id), "A lighthouse at dusk").reframe, move_id


def test_through_object_and_pedestal_down_are_their_reverses_played_backwards():
    """Oct 26: every through-object take pulled back out of the opening and pedestal down rose or tilted, while the dolly
    out and the pedestal up hold. So the reverse is rendered from the still and the picture is played backwards in code:
    the still is where the shot ends, and nothing that happens in the shot may run backwards with it."""
    assert rig.REVERSES == {"through_object", "pedestal_down"}
    subject = "A dancer in an empty ballroom"
    for move_id, twin in (("through_object", "dolly_out"), ("pedestal_down", "pedestal_up")):
        assert rig.PROMPT_AS[move_id] == twin and twin in rig.VALIDATED, "a reversed move is made from a twin that held"
    assert "through_object" in rig.VALIDATED and "pedestal_down" not in rig.VALIDATED, "Oct 26: the push through held, the descent pulled back"
    for move_id, twin in (("through_object", "dolly_out"), ("pedestal_down", "pedestal_up")):
        plan = compile_shot(CameraRig(movement=move_id), subject)
        assert plan.reverse == twin and plan.to_dict()["reverse"] == twin and plan.move_id == move_id
        assert plan.mirror is None and plan.reframe is None and plan.roll is None
        assert plan.prompt == compile_shot(CameraRig(movement=twin), subject).prompt, "LTX gets the reverse's words"
        assert plan.mode == "prompt_only" and [s.template for s in plan.segments] == ["ltx25_i2v"]
        assert "Your still is where the shot ends." in plan.notes
        assert any(n.startswith(f"reversed: the {rig.MOVES[twin].label.lower()} is rendered from your still") for n in plan.notes)
        with pytest.raises(ValueError, match="so an action would run backwards; leave the action out"):
            compile_shot(CameraRig(movement=move_id), subject, action="she spins on the spot")
        with pytest.raises(ValueError, match="the lips would move backwards against the words; leave the line out"):
            compile_shot(CameraRig(movement=move_id), subject, line="Over here.")
        assert compile_shot(CameraRig(movement=move_id), subject, action="   ").reverse == twin, "a blank action is no action"
        with pytest.raises(ValueError, match="so an effect would run backwards"):
            compile_shot(CameraRig(movement=move_id, effect="rain"), subject)
        with pytest.raises(ValueError, match="so an effect would run backwards"):
            compile_shot(CameraRig(movement=move_id, effect="ignite"), subject)
        assert rig.MOVES[move_id].describe()["reversed"] is True and rig.MOVES[twin].describe()["reversed"] is False
        assert rig.move_words(move_id)["made"] == f"Rendered as its reverse ({rig.MOVES[twin].label.lower()}), then played backwards in code."
    assert "The camera dollies out" in compile_shot(CameraRig(movement="through_object"), subject).prompt
    assert "The camera rises straight up" in compile_shot(CameraRig(movement="pedestal_down"), subject).prompt
    still = rig.compile_still_prompt(CameraRig(movement="through_object"), subject)
    assert ("Framed from just inside an open doorway or window, the edges of its frame at the very borders of the "
            "picture, the room and the subject ahead.") in still, "the still is where the push through ends"
    assert "behind an opening" not in still
    assert "Framed" not in rig.compile_still_prompt(CameraRig(movement="pedestal_down"), subject), "framed as written, like the pedestal up"
    for move_id in ("dolly_out", "pedestal_up", "static", "dutch_angle"):
        assert compile_shot(CameraRig(movement=move_id), subject).reverse is None, move_id


def test_an_extension_keeps_the_delivered_moves_words():
    """An extension continues the take the viewer saw (Oct 26, from a review of the reverse code): a reversed or mirrored
    move is rendered with its twin's words, but its continuing words name the move itself, or the camera would turn round
    at the join. A move made in code over a plain render (vertigo, a roll, a zoom) keeps the render's words."""
    subject = "Oskar at a table in a fisherman's hut at dusk, seen from the open doorway"
    rendered = compile_prompt(CameraRig(movement="through_object"), subject)
    delivered = compile_prompt(CameraRig(movement="through_object"), subject, as_delivered=True)
    assert "dollies out" in rendered and "dollies out" not in delivered
    assert delivered != rendered and "through" in delivered.lower()
    mirrored = compile_prompt(CameraRig(movement="track_left"), subject, as_delivered=True)
    assert mirrored != compile_prompt(CameraRig(movement="track_left"), subject) and "left" in mirrored.lower()
    for move_id in ("vertigo", "dutch_angle", "optical_zoom_in", "dolly_in"):
        assert compile_prompt(CameraRig(movement=move_id), subject, as_delivered=True) == compile_prompt(CameraRig(movement=move_id), subject), move_id


def test_the_arcs_are_two_stills_whose_end_still_keeps_the_subject_facing_the_scene():
    """Oct 26: arc left stood still or arced right on three renders, so the words do not set the direction. Both arcs
    are keyframed: the end still is the scene re-shot 45 degrees round, the subject's facing tied to the scene rather
    than the lens (the front-quarter angle edits kept the subject facing the camera)."""
    for move_id, side, zh in (("arc_left", "left", "向左"), ("arc_right", "right", "向右")):
        move = rig.MOVES[move_id]
        assert move.mode == "keyframed" and move.anchors == 2 and len(move.edits) == 1 and not move.featured
        edit = move.edits[0]
        assert edit == (f"Re-shoot the same scene with the camera moved 45 degrees to the {side} around the subject, at the "
                        "same distance and height. The subject does not turn: they still look toward where the camera "
                        "stood before, so the new view shows their face at a three-quarter angle and the setting behind "
                        f"them has swung round. 将镜头{zh}旋转45度，主体在场景中的朝向不变，不要转向镜头。")
        assert "facing direction" not in edit, "the angle edits' keep sentence reads to Qwen as facing the lens"
        plan = compile_shot(CameraRig(movement=move_id), "Noor on a red dune at sunset")
        assert [a.role for a in plan.anchors] == ["hero", "edit"] and plan.anchors[1].edit_prompt == edit
        assert [(s.start_anchor, s.end_anchor, s.template) for s in plan.segments] == [(0, 1, "ltx25_flf2v")]
        assert plan.mirror is None and plan.reverse is None and move_id not in rig.PROMPT_AS
        assert plan.prompt.count(side) == 1, "the video prompt names the direction once"
        assert f"arcs to the {side}" in plan.prompt and "45 degrees" in plan.prompt
        end = move.path()[-1]
        assert abs(abs(end.yaw) - 45) < 1e-6 and (end.x < 0) == (side == "left"), "the stage's last mark sits on the end still"
    assert not {"arc_left", "arc_right"} & rig.VALIDATED, "unflagged until a render holds"
    quick = compile_shot(CameraRig(movement="arc_left"), "Noor", prompt_only=True)
    assert quick.mode == "prompt_only" and [a.role for a in quick.anchors] == ["hero"], "quick mode is still one still"


def test_a_moves_page_shows_the_words_the_model_reads_and_how_a_made_move_is_made():
    dolly = rig.move_words("dolly_in")
    assert "dollies in" in dolly["words"] and "steady pace" in dolly["words"] and dolly["made"] is None
    bullet = rig.move_words("bullet_time")
    assert rig.EFFECTS["time_freeze"] in bullet["words"], "bullet time is told the frozen instant"
    assert "orbits 90 degrees" in bullet["words"], "in the 90-degree orbit's words"
    assert "mirror image (track right)" in rig.move_words("track_left")["made"]
    assert rig.move_words("arc_right")["made"] is None, "an arc is two stills; nothing about it is made in code"
    assert rig.move_words("vertigo")["made"].endswith("The zoom follows the face it finds in the render.")
    assert "1.5x" in rig.move_words("optical_zoom_in")["made"]
    assert "turned 15 degrees in code" in rig.move_words("dutch_angle")["made"]
    described = {m["id"]: m for m in rig.catalog()["moves"]}
    assert all(m["words"] for m in described.values()), "every move in the catalog carries its words"
    assert described["track_left"]["made"] and not described["track_right"]["made"]
