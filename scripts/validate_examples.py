import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from openfield.services.camera_compiler import CameraRig, compile_rig
from openfield.services.openjutsu_service import OpenJutsuRequest, build_openjutsu_workflow
from openfield.services.preflight import validate_workflow


def main() -> int:
    root = Path(__file__).parents[1]
    cinema = json.loads((root / "examples/cinema_rig.json").read_text())
    compiled = compile_rig(CameraRig(**cinema["rig"]), cinema["subject_prompt"])
    assert compiled["required_nodes"]
    for name in ("openjutsu_ltx.json", "multi_angle_qwen.json"):
        data = json.loads((root / "examples" / name).read_text())
        request = OpenJutsuRequest(**{k: data[k] for k in (
            "source_video", "references", "prompt", "backend",
            "duration_seconds", "preserve_audio", "mode"
        )})
        graph = build_openjutsu_workflow(request)
        missing = validate_workflow(graph, {
            *({"LoadVideo", "LoadImage", "LTXVPreprocess", "LTXVAddGuide",
               "LTXVConditioning", "LTXVImgToVideo", "LTXVAudioVAEDecode", "SaveVideo"}
              if request.backend == "ltx" else
              {"LoadImage", "TextEncodeQwenImageEditPlus", "QwenImageEditPlus", "SaveImage"})
        })
        assert not missing, f"{name}: missing {missing}"
    print("PASS: examples compile and pass declared capability preflight")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
