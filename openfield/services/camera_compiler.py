from dataclasses import asdict, dataclass
from typing import Any


SENSORS = ("modern_digital", "35mm_film", "8mm_film", "dv_camcorder")
LENSES = ("clean_sharp", "anamorphic", "vintage_anamorphic", "warm_vintage", "halation_vintage")
APERTURES = ("f1.4", "f4", "f11")
LIGHTING = ("auto", "soft_cross", "overhead_fall", "contre_jour", "window", "practicals", "silhouette")
MOVES = (
    "static", "pan_left", "pan_right", "tilt_up", "tilt_down", "dolly_in", "dolly_out",
    "optical_zoom_in", "optical_zoom_out", "orbit_90", "orbit_180", "orbit_360",
    "track_left", "track_right", "crane_up", "crane_down", "pedestal_up", "pedestal_down",
    "arc_left", "arc_right", "push_in", "pull_out", "truck_left", "truck_right",
    "handheld", "fpv_drone", "robot_arm", "helicopter", "whip_pan", "rack_focus",
    "vertigo", "top_down", "low_angle", "over_shoulder", "reveal",
)


@dataclass(frozen=True)
class CameraRig:
    sensor: str = "modern_digital"
    lens: str = "clean_sharp"
    focal_length_mm: int = 35
    aperture: str = "f4"
    lighting: str = "soft_cross"
    movement: str = "static"
    duration_seconds: float = 5.0
    speed: str = "linear"
    start_frame: str | None = None
    end_frame: str | None = None

    def validate(self) -> None:
        if self.sensor not in SENSORS:
            raise ValueError(f"unsupported sensor: {self.sensor}")
        if self.lens not in LENSES:
            raise ValueError(f"unsupported lens: {self.lens}")
        if self.aperture not in APERTURES:
            raise ValueError(f"unsupported aperture: {self.aperture}")
        if self.lighting not in LIGHTING:
            raise ValueError(f"unsupported lighting: {self.lighting}")
        if self.movement not in MOVES:
            raise ValueError(f"unsupported movement: {self.movement}")
        if not 8 <= self.focal_length_mm <= 200:
            raise ValueError("focal_length_mm must be between 8 and 200")
        if not 1 <= self.duration_seconds <= 30:
            raise ValueError("duration_seconds must be between 1 and 30")


def _anti_drift(rig: CameraRig) -> str:
    if rig.movement.startswith("optical_zoom"):
        return "locked tripod, zero camera travel, zero parallax, optical lens change only"
    if rig.movement.startswith(("orbit", "arc")):
        return "constant radius, constant height, subject remains centered, no subject spin"
    if rig.movement.startswith(("dolly", "push", "pull")):
        return "physical camera travel, fixed focal length, no zoom, constant lens height"
    return "one continuous move, no unrequested pan, tilt, zoom, or camera drift"


def compile_camera_prompt(rig: CameraRig, subject_prompt: str) -> str:
    rig.validate()
    return (
        f"{subject_prompt}. Cinematography: {rig.sensor.replace('_', ' ')}, "
        f"{rig.lens.replace('_', ' ')} lens, {rig.focal_length_mm}mm, aperture {rig.aperture}, "
        f"{rig.lighting.replace('_', '-')}; one continuous {rig.movement.replace('_', ' ')} "
        f"at {rig.speed} speed for {rig.duration_seconds:g} seconds. {_anti_drift(rig)}."
    )


def compile_rig(rig: CameraRig, subject_prompt: str) -> dict[str, Any]:
    rig.validate()
    prompt = compile_camera_prompt(rig, subject_prompt)
    camera_nodes = ["LoadImage", "MiniMaxH3ImageToVideo", "SaveVideo"]
    if rig.movement != "static":
        camera_nodes = ["LoadImage", "WanCameraEmbedding", "WanCameraImageToVideo", "SaveVideo"]
    if rig.start_frame and rig.end_frame:
        camera_nodes.insert(-1, "FrameTweenGuide")
    return {
        "rig": asdict(rig),
        "prompt": prompt,
        "anti_drift": _anti_drift(rig),
        "supports_start_end_tween": bool(rig.start_frame and rig.end_frame),
        "required_nodes": camera_nodes,
    }
