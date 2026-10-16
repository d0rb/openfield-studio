from openfield.platform import PlatformClient, PlatformError
from openfield.services.camera_compiler import CameraRig, compile_rig
from openfield.services.openjutsu_service import OpenJutsuRequest, build_openjutsu_workflow


def test_camera_compiler_locks_optical_zoom():
    result = compile_rig(CameraRig(movement="optical_zoom_in"), "a lighthouse",)
    assert "zero parallax" in result["anti_drift"]
    assert "optical zoom" in result["prompt"]


def test_start_end_tween_is_declared():
    result = compile_rig(CameraRig(start_frame="a.png", end_frame="b.png"), "a room")
    assert result["supports_start_end_tween"] is True


def test_openjutsu_ltx_graph_has_capability_contract():
    request = OpenJutsuRequest("clip.mp4", ["ref.png"], backend="ltx")
    graph = build_openjutsu_workflow(request)
    assert graph["4"]["class_type"] == "LTXVAddGuide"
    assert graph["8"]["class_type"] == "SaveVideo"


def test_openjutsu_qwen_angle_graph_is_image_only():
    request = OpenJutsuRequest("clip.mp4", ["ref.png"], backend="qwen", mode="multi_angle")
    graph = build_openjutsu_workflow(request)
    assert graph["4"]["class_type"] == "SaveImage"


def test_open_weights_policy_blocks_unknown_router_model():
    client = PlatformClient(mode="dryrun", open_weights_only=True)
    try:
        client.submit_router("closed/provider-model", {})
    except PlatformError:
        return
    raise AssertionError("closed model was not blocked")
