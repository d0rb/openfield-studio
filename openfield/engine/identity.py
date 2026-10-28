"""Local face check behind the identity ring: does a generated face still match the Cast?

YuNet finds faces and SFace embeds them, both through OpenCV's DNN face API. The gate only
reports what it measured: models that are missing or fail to run give "unavailable", shots
without a usable face give "n/a", and neither can ever read as a match.

    python -m openfield.engine.identity REF [REF...] -- CANDIDATE [--json] [--download]
        [--no-enlarge]

Exit status: 0 pass, 1 drift, 2 n/a or unavailable.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import sys
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import cv2
import httpx
import numpy as np

from ..fsutil import replace_file

__all__ = [
    "DETECTOR_FILE",
    "ENLARGE_TARGET_PX",
    "MODELS",
    "RECOGNIZER_FILE",
    "SFACE_COSINE_THRESHOLD",
    "SMALL_FACE_PX",
    "Face",
    "FaceGate",
    "IdentityReport",
    "ModelDownloadError",
    "ModelSpec",
    "cosine_similarity",
    "default_model_dir",
    "download_models",
    "main",
]

log = logging.getLogger(__name__)

DETECTOR_FILE = "face_detection_yunet_2023mar.onnx"
RECOGNIZER_FILE = "face_recognition_sface_2021dec.onnx"
SFACE_COSINE_THRESHOLD = 0.363  # same-identity boundary from the OpenCV Zoo SFace model card
MAX_DETECT_SIDE = 2048  # larger images are detected on a downscaled copy, boxes mapped back
DETECT_SIDES = (MAX_DETECT_SIDE, 960, 480)  # scales tried in order until a face is found
SMALL_FACE_PX = 80  # a candidate face whose short side is under this is enlarged before embedding
ENLARGE_TARGET_PX = 160  # enlarged candidate crop aim; the scale factor is capped at 4x

_DETECT_SCORE = 0.7
_DETECT_NMS = 0.3
_DETECT_TOP_K = 5000
_LANDMARKS = 5
_ROW_LEN = 15  # YuNet row: x, y, w, h, five (x, y) landmarks, score
_CHUNK = 1 << 20
_DOWNLOAD_HINT = "run `python -m openfield.engine.identity --download`"
_EXIT_CODES = {"pass": 0, "drift": 1, "n/a": 2, "unavailable": 2}
_EXIT_ERROR = 2
_FLAGS = ("--json", "--download", "--no-enlarge")
_USAGE = (
    "usage: python -m openfield.engine.identity REF [REF...] -- CANDIDATE "
    "[--json] [--download] [--no-enlarge]"
)
_HELP = "  --no-enlarge  compare the face at its original size (no enlargement of small faces)"

ImageLike = str | os.PathLike | np.ndarray
Box = tuple[int, int, int, int]


class _Detector(Protocol):
    def setInputSize(self, size: tuple[int, int]) -> None: ...

    def detect(self, image: np.ndarray) -> tuple[Any, np.ndarray | None]: ...


class _Recognizer(Protocol):
    def alignCrop(self, image: np.ndarray, face_row: np.ndarray) -> np.ndarray: ...

    def feature(self, aligned: np.ndarray) -> np.ndarray: ...


@dataclass(frozen=True)
class ModelSpec:
    file: str
    url: str
    sha256: str | None
    min_bytes: int


_ZOO = "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models"

# sha256 values were pinned from opencv_zoo main as fetched on 2026-10-16.
MODELS: dict[str, ModelSpec] = {
    "detector": ModelSpec(
        file=DETECTOR_FILE,
        url=f"{_ZOO}/face_detection_yunet/{DETECTOR_FILE}",
        sha256="8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
        min_bytes=100_000,
    ),
    "recognizer": ModelSpec(
        file=RECOGNIZER_FILE,
        url=f"{_ZOO}/face_recognition_sface/{RECOGNIZER_FILE}",
        sha256="0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
        min_bytes=30_000_000,
    ),
}


class ModelDownloadError(RuntimeError):
    """A model file could not be fetched, or what arrived was not the pinned model."""


def default_model_dir() -> Path:
    root = os.environ.get("OPENFIELD_MODEL_DIR")
    if root:
        return Path(root) / "face"
    home = Path.home() / ".cache" / "openfield" / "models" / "face"
    if str(home).isascii():
        return home
    # OpenCV's ONNX loader cannot open non-ASCII paths on Windows: use a shared ASCII location
    for variable in ("PUBLIC", "ProgramData"):
        base = os.environ.get(variable)
        if base and base.isascii():
            return Path(base) / "openfield" / "models" / "face"
    return home


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(_CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def _problem(spec: ModelSpec, size: int, digest: str) -> str | None:
    if size < spec.min_bytes:
        return (
            f"{size} bytes is below the {spec.min_bytes}-byte minimum "
            "(a Git-LFS pointer or an error page, not the model)"
        )
    if spec.sha256 is not None and digest != spec.sha256:
        return f"sha256 {digest} does not match the pinned {spec.sha256}"
    return None


def _is_valid(spec: ModelSpec, path: Path) -> bool:
    if not path.is_file():
        return False
    return _problem(spec, path.stat().st_size, _sha256_of(path)) is None


def _session(client: httpx.Client | None) -> contextlib.AbstractContextManager[httpx.Client]:
    if client is not None:
        return contextlib.nullcontext(client)
    return httpx.Client(timeout=httpx.Timeout(60.0, connect=20.0))


def _fetch(client: httpx.Client, spec: ModelSpec, target: Path) -> None:
    part = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    size = 0
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with client.stream("GET", spec.url, follow_redirects=True) as response:
            response.raise_for_status()
            with part.open("wb") as out:
                for chunk in response.iter_bytes(_CHUNK):
                    out.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
        problem = _problem(spec, size, digest.hexdigest())
        if problem is not None:
            raise ModelDownloadError(f"{spec.file}: {problem}")
        replace_file(part, target)
    except (httpx.HTTPError, OSError) as exc:
        raise ModelDownloadError(f"{spec.file}: download from {spec.url} failed: {exc}") from exc
    finally:
        part.unlink(missing_ok=True)


def download_models(dest: Path | None = None, *, client: httpx.Client | None = None) -> list[Path]:
    """Fetch the model files that are missing or fail validation; return all paths in MODELS order.

    A file only ever appears under its final name after its size and sha256 check out. Requests
    carry no credentials; pass ``client`` to bring your own proxy or certificate setup.
    """
    folder = Path(dest) if dest is not None else default_model_dir()
    wanted = [(spec, folder / spec.file) for spec in MODELS.values()]
    stale = [(spec, path) for spec, path in wanted if not _is_valid(spec, path)]
    if stale:
        with _session(client) as http:
            for spec, path in stale:
                _fetch(http, spec, path)
    return [path for _, path in wanted]


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine of the angle between two embeddings, as FaceRecognizerSF.match(FR_COSINE) gives it.

    Computed here because match() normalises its arguments in place, which would silently
    rewrite cached embeddings.
    """
    x = np.asarray(a, dtype=np.float64).ravel()
    y = np.asarray(b, dtype=np.float64).ravel()
    norm = float(np.linalg.norm(x) * np.linalg.norm(y))
    if not 0.0 < norm < np.inf:
        raise ValueError("cannot compare an empty, zero or non-finite embedding")
    return max(-1.0, min(1.0, float(np.dot(x, y) / norm)))


@dataclass(frozen=True)
class Face:
    """A detected face; ``box`` is (x, y, w, h) in pixels of the original image."""

    box: Box
    score: float
    landmarks: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class IdentityReport:
    """What the gate measured.

    status is "pass" (best cosine at or above threshold), "drift" (below it), "n/a" (nothing to
    compare: unreadable input, no face in the candidate, no usable reference) or "unavailable"
    (the face models could not run). score is None unless a comparison happened; best_ref and
    per_ref index into the references as given, with None where a reference had no usable face.
    face_px is the short side of the candidate's largest face; enlarged is the factor applied to
    a small-face crop before embedding, or None when the original image was embedded.
    """

    status: str
    score: float | None
    threshold: float
    best_ref: int | None
    per_ref: tuple[float | None, ...]
    faces_in_candidate: int
    candidate_box: Box | None
    refs_used: int
    reason: str
    face_px: int | None = None
    enlarged: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "score": self.score,
            "threshold": self.threshold,
            "best_ref": self.best_ref,
            "per_ref": list(self.per_ref),
            "faces_in_candidate": self.faces_in_candidate,
            "candidate_box": None if self.candidate_box is None else list(self.candidate_box),
            "refs_used": self.refs_used,
            "reason": self.reason,
            "face_px": self.face_px,
            "enlarged": self.enlarged,
        }


def _unmeasured(
    status: str,
    reason: str,
    threshold: float,
    n_refs: int,
    *,
    faces: int = 0,
    box: Box | None = None,
    face_px: int | None = None,
    enlarged: float | None = None,
) -> IdentityReport:
    return IdentityReport(
        status=status,
        score=None,
        threshold=threshold,
        best_ref=None,
        per_ref=(None,) * n_refs,
        faces_in_candidate=faces,
        candidate_box=box,
        refs_used=0,
        reason=reason,
        face_px=face_px,
        enlarged=enlarged,
    )


def _scored(
    per_ref: tuple[float | None, ...],
    faces: int,
    box: Box,
    threshold: float,
    *,
    face_px: int | None = None,
    enlarged: float | None = None,
) -> IdentityReport:
    best = max((i for i, s in enumerate(per_ref) if s is not None), key=per_ref.__getitem__)
    score = per_ref[best]
    passed = score >= threshold
    relation = ">=" if passed else "<"
    return IdentityReport(
        status="pass" if passed else "drift",
        score=score,
        threshold=threshold,
        best_ref=best,
        per_ref=per_ref,
        faces_in_candidate=faces,
        candidate_box=box,
        refs_used=sum(s is not None for s in per_ref),
        reason=f"cosine {score:.3f} {relation} threshold {threshold:.3f} (best reference {best})",
        face_px=face_px,
        enlarged=enlarged,
    )


def _as_bgr(array: np.ndarray) -> np.ndarray | None:
    if array.dtype != np.uint8 or array.size == 0:
        return None
    if array.ndim == 2:
        return cv2.cvtColor(array, cv2.COLOR_GRAY2BGR)
    if array.ndim == 3 and array.shape[2] == 3:
        return array
    if array.ndim == 3 and array.shape[2] == 4:
        return cv2.cvtColor(array, cv2.COLOR_BGRA2BGR)
    return None


def _read_image(source: ImageLike) -> tuple[np.ndarray | None, str]:
    """Decode to a BGR uint8 array: (image, "") or (None, why). Never raises."""
    if isinstance(source, np.ndarray):
        image = _as_bgr(source)
        if image is None:
            return None, "expected a non-empty uint8 array shaped (H, W), (H, W, 3) or (H, W, 4)"
        return image, ""
    try:
        # fromfile + imdecode rather than imread: imread cannot open non-ASCII Windows paths
        data = np.fromfile(os.fspath(source), dtype=np.uint8)
        image = cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None
    except (OSError, TypeError, ValueError, cv2.error) as exc:
        return None, f"cannot read {source!r}: {exc}"
    if image is None:
        return None, f"not a decodable image: {source}"
    return image, ""


def _shrink(image: np.ndarray, limit: int = MAX_DETECT_SIDE) -> tuple[np.ndarray, float, float]:
    """Downscale past `limit`; also return the per-axis factors back to full size."""
    height, width = image.shape[:2]
    longest = max(height, width)
    if longest <= limit:
        return image, 1.0, 1.0
    ratio = limit / longest
    new_w, new_h = max(1, round(width * ratio)), max(1, round(height * ratio))
    small = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
    return small, width / new_w, height / new_h


def _clip(value: float, limit: int) -> int:
    return min(max(round(value), 0), limit)


def _to_face(row: list[float], sx: float, sy: float, width: int, height: int) -> Face:
    x, y, w, h, *marks, score = row
    left, top = _clip(x * sx, width), _clip(y * sy, height)
    right, bottom = _clip((x + w) * sx, width), _clip((y + h) * sy, height)
    landmarks = tuple((marks[i] * sx, marks[i + 1] * sy) for i in range(0, len(marks), 2))
    return Face((left, top, right - left, bottom - top), score, landmarks)


def _detection_row(face: Face) -> np.ndarray:
    if len(face.landmarks) != _LANDMARKS:
        raise ValueError(f"alignment needs {_LANDMARKS} landmarks, got {len(face.landmarks)}")
    marks = [coord for point in face.landmarks for coord in point]
    return np.array([[*face.box, *marks, face.score]], dtype=np.float32)


def _as_list(references: Any) -> list[Any]:
    if references is None:
        return []
    if isinstance(references, (str, os.PathLike)):
        return [references]
    return list(references)


class FaceGate:
    """Same-identity check between reference faces and a candidate image.

    OpenCV's detector and recognizer are stateful, so the public methods take a lock: the app shares one
    gate between a take's identity check and a cast upload running on different threads.
    ``detector`` and ``recognizer`` replace the OpenCV models, which lets tests inject fakes.

    With ``enlarge`` (the default), a candidate whose largest face has a short side under
    SMALL_FACE_PX is detected again on an upscaled crop around that face, and the embedding comes
    from the crop: SFace is unreliable on tiny faces. References are never enlarged. The report
    records face_px (the original face's short side) and enlarged (the crop's scale factor, or
    None when the original image was embedded).
    """

    def __init__(
        self,
        model_dir: Path | str | None = None,
        *,
        detector: _Detector | None = None,
        recognizer: _Recognizer | None = None,
        enlarge: bool = True,
    ) -> None:
        self.model_dir = Path(model_dir) if model_dir is not None else default_model_dir()
        self.enlarge = enlarge
        self.available = False
        self.reason = "not initialised"
        self._detector = detector
        self._recognizer = recognizer
        self._cache: dict[str, tuple[int, np.ndarray | None]] = {}
        self._lock = threading.RLock()
        try:
            self._open_models()
        except Exception as exc:  # corrupt model file, odd OpenCV build, ...
            self.reason = f"face models unavailable: {type(exc).__name__}: {exc}"
            if isinstance(exc, cv2.error) and not str(self.model_dir).isascii():
                self.reason += (
                    "; if the folder name has non-ASCII characters, OpenCV on Windows cannot "
                    "open it: set OPENFIELD_MODEL_DIR to an ASCII path"
                )

    def _model_file(self, role: str) -> Path:
        spec = MODELS[role]
        path = self.model_dir / spec.file
        if not path.is_file():
            raise FileNotFoundError(f"{path} is missing; {_DOWNLOAD_HINT}")
        size = path.stat().st_size
        if size < spec.min_bytes:
            raise ValueError(
                f"{path} is {size} bytes, a Git-LFS pointer, not a model; {_DOWNLOAD_HINT}"
            )
        return path

    def _open_models(self) -> None:
        if self._detector is None:
            self._detector = cv2.FaceDetectorYN.create(
                str(self._model_file("detector")),
                "",
                (320, 320),
                _DETECT_SCORE,
                _DETECT_NMS,
                _DETECT_TOP_K,
            )
        if self._recognizer is None:
            self._recognizer = cv2.FaceRecognizerSF.create(str(self._model_file("recognizer")), "")
        self.available = True
        self.reason = "ok"

    def status(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "reason": self.reason,
            "model_dir": str(self.model_dir),
            "detector": DETECTOR_FILE,
            "recognizer": RECOGNIZER_FILE,
            "threshold": SFACE_COSINE_THRESHOLD,
            "cached_refs": len(self._cache),
        }

    def _detect(self, image: np.ndarray) -> list[Face]:
        """Largest-first faces. YuNet only finds faces of roughly 10-300 px, so a close-up in a
        large frame is missed at full size and found after shrinking: try smaller scales on a miss.
        """
        height, width = image.shape[:2]
        tried: set[tuple[int, int]] = set()
        for limit in DETECT_SIDES:
            small, sx, sy = _shrink(image, limit)
            if small.shape[:2] in tried:
                continue
            tried.add(small.shape[:2])
            self._detector.setInputSize((small.shape[1], small.shape[0]))
            _, rows = self._detector.detect(small)
            if rows is None:
                continue
            flat = np.asarray(rows, dtype=np.float32).reshape(-1, _ROW_LEN).tolist()
            faces = [_to_face(row, sx, sy, width, height) for row in flat]
            return sorted(faces, key=lambda f: f.box[2] * f.box[3], reverse=True)
        return []

    def _embed_face(self, image: np.ndarray, face: Face) -> np.ndarray:
        aligned = self._recognizer.alignCrop(image, _detection_row(face))
        return np.array(self._recognizer.feature(aligned), dtype=np.float32).reshape(-1)

    def _embed(self, source: ImageLike, face: Face | None) -> np.ndarray | None:
        image, _ = _read_image(source)
        if image is None:
            return None
        if face is None:
            found = self._detect(image)
            if not found:
                return None
            face = found[0]
        return self._embed_face(image, face)

    def _reference_embedding(self, source: ImageLike) -> np.ndarray | None:
        """Embedding of a reference's largest face, cached by (absolute path, mtime_ns)."""
        try:
            key = os.path.abspath(source)
            stamp = os.stat(key).st_mtime_ns
        except (OSError, TypeError, ValueError):
            return None
        hit = self._cache.get(key)
        if hit is not None and hit[0] == stamp:
            return hit[1]
        try:
            embedding = self._embed(key, None)
        except Exception as exc:
            log.warning("reference %s skipped: %s", key, exc)
            return None
        self._cache[key] = (stamp, embedding)
        return embedding

    def faces(self, image: ImageLike) -> list[Face]:
        """Faces in a path or a BGR uint8 array, largest first; [] on any failure."""
        if not self.available:
            return []
        try:
            decoded, _ = _read_image(image)
            with self._lock:
                return [] if decoded is None else self._detect(decoded)
        except Exception as exc:
            log.warning("face detection failed: %s", exc)
            return []

    def embed(self, image: ImageLike, face: Face | None = None) -> np.ndarray | None:
        """SFace feature (128 float32) of ``face``, or of the largest face when omitted."""
        if not self.available:
            return None
        try:
            with self._lock:
                return self._embed(image, face)
        except Exception as exc:
            log.warning("embedding failed: %s", exc)
            return None

    def check(
        self,
        references: Sequence[str | Path],
        candidate: ImageLike,
        *,
        threshold: float = SFACE_COSINE_THRESHOLD,
    ) -> IdentityReport:
        """Compare the candidate's largest face with every reference face; see IdentityReport."""
        refs = _as_list(references)
        if not self.available:
            return _unmeasured("unavailable", self.reason, threshold, len(refs))
        try:
            with self._lock:
                return self._compare(refs, candidate, threshold)
        except Exception as exc:
            reason = f"identity check failed: {type(exc).__name__}: {exc}"
            return _unmeasured("unavailable", reason, threshold, len(refs))

    def _compare(self, refs: list[Any], candidate: ImageLike, threshold: float) -> IdentityReport:
        if not refs:
            return _unmeasured("n/a", "no reference images given", threshold, 0)
        image, why = _read_image(candidate)
        if image is None:
            return _unmeasured("n/a", f"candidate unreadable: {why}", threshold, len(refs))
        found = self._detect(image)
        if not found:
            return _unmeasured("n/a", "no face detected in the candidate", threshold, len(refs))
        box = found[0].box
        short = min(box[2], box[3])
        face_px = int(short)
        enlarged = None
        embed_image, embed_face = image, found[0]
        if self.enlarge and 0 < short < SMALL_FACE_PX:
            factor = min(4.0, ENLARGE_TARGET_PX / short)
            x, y, w, h = box
            left, top = max(0, x - w), max(0, y - h)
            right, bottom = min(image.shape[1], x + 2 * w), min(image.shape[0], y + 2 * h)
            crop = image[top:bottom, left:right]
            if crop.size:
                size = (max(1, round(crop.shape[1] * factor)), max(1, round(crop.shape[0] * factor)))
                upscaled = cv2.resize(crop, size, interpolation=cv2.INTER_CUBIC)
                inside = self._detect(upscaled)
                if inside:
                    embed_image, embed_face = upscaled, inside[0]
                    enlarged = round(factor, 2)
        embeddings = [self._reference_embedding(ref) for ref in refs]
        if all(e is None for e in embeddings):
            reason = f"no face found in any of the {len(refs)} reference image(s)"
            return _unmeasured(
                "n/a",
                reason,
                threshold,
                len(refs),
                faces=len(found),
                box=box,
                face_px=face_px,
                enlarged=enlarged,
            )
        target = self._embed_face(embed_image, embed_face)
        per_ref = tuple(None if e is None else cosine_similarity(e, target) for e in embeddings)
        return _scored(
            per_ref,
            len(found),
            box,
            threshold,
            face_px=face_px,
            enlarged=enlarged,
        )


def _download_for_cli() -> bool:
    try:
        paths = download_models()
    except ModelDownloadError as exc:
        print(f"download failed: {exc}", file=sys.stderr)
        return False
    for path in paths:
        print(f"model ready: {path}", file=sys.stderr)
    return True


def _split_paths(words: list[str]) -> tuple[list[str], list[str]]:
    """Split ``REF... -- CANDIDATE``; without the ``--`` the last word is the candidate."""
    if "--" in words:
        cut = words.index("--")
        return words[:cut], words[cut + 1 :]
    return words[:-1], words[-1:]


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "-h" in args or "--help" in args:
        print(_USAGE)
        print(_HELP)
        return 0
    words = [arg for arg in args if arg not in _FLAGS]
    if "--download" in args:
        if not _download_for_cli():
            return _EXIT_ERROR
        if not words:
            return 0
    refs, candidate = _split_paths(words)
    if not refs or len(candidate) != 1:
        print(_USAGE, file=sys.stderr)
        return _EXIT_ERROR
    gate = FaceGate(enlarge=False) if "--no-enlarge" in args else FaceGate()
    report = gate.check(refs, candidate[0])
    if "--json" in args:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(f"{report.status}: {report.reason}")
    return _EXIT_CODES[report.status]


if __name__ == "__main__":
    sys.exit(main())
