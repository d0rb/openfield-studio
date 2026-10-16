from pathlib import Path
from typing import Any


class IdentityGate:
    """Optional YuNet/SFace gate with a safe unavailable state."""

    def __init__(self, model_dir: str | Path = "models/face"):
        self.model_dir = Path(model_dir)
        self.available = False
        self.reason = "opencv models are not installed"
        try:
            import cv2  # noqa: F401
            detector = self.model_dir / "face_detection_yunet_2023mar.onnx"
            recognizer = self.model_dir / "face_recognition_sface_2021dec.onnx"
            self.available = detector.stat().st_size > 10240 and recognizer.stat().st_size > 10240
            self.reason = "ready" if self.available else "model files are missing or incomplete"
        except Exception as exc:
            self.reason = str(exc)

    def verdict(self, references: list[str], candidate: str) -> dict[str, Any]:
        if not self.available:
            return {"available": False, "same": None, "score": None, "reason": self.reason}
        # Full inference is deliberately kept behind the optional dependency
        # boundary; the production pipeline must never treat unavailable as a
        # positive identity match.
        return {"available": True, "same": None, "score": None, "reason": "inference adapter not invoked"}
