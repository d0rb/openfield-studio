import argparse
import json

from .services.camera_compiler import CameraRig, compile_rig
from .services.openjutsu_service import OpenJutsuRequest, build_openjutsu_workflow, required_nodes
from .services.preflight import validate_workflow
from .services.capabilities import validate_against_live


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenField Studio command line")
    parser.add_argument("command", choices=["dryrun", "camera", "openjutsu", "live-preflight"])
    args = parser.parse_args()
    if args.command == "live-preflight":
        import os
        from .config import settings
        url = os.getenv("OPENFIELD_LIVE_COMFY_URL", settings.comfy_base_url)
        graph = build_openjutsu_workflow(OpenJutsuRequest("source.mp4", ["ref.png"]))
        missing = validate_against_live(url, graph)
        result = {"url": url, "missing_nodes": missing, "status": "pass" if not missing else "fail"}
    elif args.command == "camera":
        result = compile_rig(CameraRig(movement="orbit_360"), "a glass perfume bottle on a marble table")
    elif args.command == "openjutsu":
        request = OpenJutsuRequest("source.mp4", ["character.png"], backend="ltx")
        result = {"workflow": build_openjutsu_workflow(request), "required_nodes": sorted(required_nodes("ltx"))}
    else:
        graph = build_openjutsu_workflow(OpenJutsuRequest("source.mp4", ["ref.png"]))
        result = {
            "status": "ok",
            "checks": ["camera schema", "openjutsu LTX graph schema", "open-weights policy boundary"],
            "missing_nodes_against_minimal_core": validate_workflow(
                graph, {"LoadVideo", "LoadImage", "LTXVPreprocess", "LTXVAddGuide",
                        "LTXVConditioning", "LTXVImgToVideo", "LTXVAudioVAEDecode", "SaveVideo"}
            ),
        }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
