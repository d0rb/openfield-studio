"""Unit tests for the identity gate: injected fakes only, no real faces, no network."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import httpx
import numpy as np
import pytest
from PIL import Image

from openfield.engine import identity
from openfield.engine.identity import (
    DETECTOR_FILE,
    MODELS,
    SFACE_COSINE_THRESHOLD,
    Face,
    FaceGate,
    ModelDownloadError,
    ModelSpec,
    cosine_similarity,
    default_model_dir,
    download_models,
    main,
)

LFS_POINTER = b"version https://git-lfs.github.com/spec/v1\noid sha256:" + b"0" * 64 + b"\nsize 1\n"
PAYLOADS = {"detector": b"detector-weights-" * 200, "recognizer": b"recognizer-weights-" * 300}


def face_row(x: float, y: float, w: float, h: float, score: float = 0.99) -> list[float]:
    marks: list[float] = []
    for fx, fy in ((0.3, 0.35), (0.7, 0.35), (0.5, 0.55), (0.35, 0.75), (0.65, 0.75)):
        marks += [x + fx * w, y + fy * h]
    return [x, y, w, h, *marks, score]


class FakeDetector:
    """Reports the faces scripted for the image's top-left pixel value; none otherwise."""

    def __init__(self, faces: dict[int, list[list[float]]] | None = None) -> None:
        self.faces = faces or {}
        self.sizes: list[tuple[int, int]] = []
        self.seen: list[tuple[int, int]] = []

    def setInputSize(self, size: tuple[int, int]) -> None:
        self.sizes.append(size)

    def detect(self, image: np.ndarray) -> tuple[int, np.ndarray | None]:
        self.seen.append(image.shape[:2])
        rows = self.faces.get(int(image[0, 0, 0]))
        return (1, np.array(rows, dtype=np.float32)) if rows else (1, None)


class FakeRecognizer:
    """Embeds by the image's top-left pixel value and hands back the same array every time."""

    def __init__(self, vectors: dict[int, list[float]]) -> None:
        self.vectors = {k: np.array([v], dtype=np.float32) for k, v in vectors.items()}
        self.feature_calls = 0
        self.widths: list[int] = []

    def alignCrop(self, image: np.ndarray, face_row: np.ndarray) -> int:
        self.widths.append(int(face_row[0, 2]))
        return int(image[0, 0, 0])

    def feature(self, aligned: int) -> np.ndarray:
        self.feature_calls += 1
        return self.vectors[aligned]


def write_png(path: Path, code: int, size: int = 64) -> Path:
    Image.fromarray(np.full((size, size, 3), code, dtype=np.uint8)).save(path)
    return path


class Rig:
    """A FaceGate on fakes plus flat-colour PNGs whose colour selects what the fakes report."""

    def __init__(self, folder: Path, faces: dict, vectors: dict) -> None:
        self.folder = folder
        self.detector = FakeDetector(faces)
        self.recognizer = FakeRecognizer(vectors)
        self.gate = FaceGate(folder / "models", detector=self.detector, recognizer=self.recognizer)

    def image(self, name: str, code: int) -> Path:
        return write_png(self.folder / name, code)


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    """1 and 2 are orthogonal identities, 3 is close to 1, 4 is unrelated to both."""
    faces = {code: [face_row(8, 8, 40, 40)] for code in (1, 2, 3, 4)}
    vectors = {1: [1, 0, 0, 0], 2: [0, 1, 0, 0], 3: [0.9, 0.1, 0, 0], 4: [0, 0, 1, 0]}
    return Rig(tmp_path, faces, vectors)


# --- similarity -------------------------------------------------------------------------


def test_cosine_similarity_known_values():
    assert cosine_similarity(np.array([1, 0]), np.array([1, 0])) == pytest.approx(1.0)
    assert cosine_similarity(np.array([1, 0]), np.array([0, 1])) == pytest.approx(0.0)
    assert cosine_similarity(np.array([1, 0]), np.array([-1, 0])) == pytest.approx(-1.0)
    assert cosine_similarity(np.array([3, 4]), np.array([4, 3])) == pytest.approx(0.96)


def test_cosine_similarity_ignores_scale_and_shape_and_leaves_inputs_alone():
    a = np.array([[0.5, 1.5, -2.0, 4.0]], dtype=np.float32)
    b = np.array([2.0, 1.0, 0.0, -1.0], dtype=np.float32)
    a_before, b_before = a.copy(), b.copy()
    base = cosine_similarity(a, b)
    assert cosine_similarity(a * 7, b / 3) == pytest.approx(base)
    assert np.array_equal(a, a_before)
    assert np.array_equal(b, b_before)


@pytest.mark.parametrize("seed", [0, 1, 4])
def test_cosine_similarity_stays_within_bounds_despite_rounding(seed):
    v = np.random.default_rng(seed).normal(size=128).astype(np.float32)
    assert cosine_similarity(v, v) == 1.0
    assert cosine_similarity(v, -v) == -1.0


@pytest.mark.parametrize("bad", [[0.0, 0.0, 0.0], [np.nan, 1.0, 0.0], [np.inf, 1.0, 0.0], []])
def test_cosine_similarity_refuses_degenerate_vectors(bad):
    with pytest.raises(ValueError):
        cosine_similarity(np.array(bad), np.array([1.0, 0.0, 0.0]))


# --- check() verdicts -------------------------------------------------------------------


def test_close_candidate_passes_and_unrelated_candidate_drifts(rig):
    ref = rig.image("a.png", 1)
    near = rig.gate.check([ref], rig.image("near.png", 3))
    far = rig.gate.check([ref], rig.image("far.png", 4))
    assert near.status == "pass"
    assert near.score == pytest.approx(0.9 / (0.82**0.5), abs=1e-4)
    assert near.threshold == SFACE_COSINE_THRESHOLD == 0.363
    assert (near.faces_in_candidate, near.candidate_box) == (1, (8, 8, 40, 40))
    assert far.status == "drift"
    assert far.score == pytest.approx(0.0)


def test_score_equal_to_the_threshold_passes(rig):
    ref, candidate = rig.image("a.png", 1), rig.image("c.png", 3)
    score = rig.gate.check([ref], candidate).score
    at = rig.gate.check([ref], candidate, threshold=score)
    above = rig.gate.check([ref], candidate, threshold=float(np.nextafter(score, 2.0)))
    assert (at.status, above.status) == ("pass", "drift")


def test_best_reference_wins_and_per_ref_follows_input_order(rig):
    far_ref, near_ref = rig.image("b.png", 2), rig.image("a.png", 1)
    report = rig.gate.check([far_ref, near_ref], rig.image("c.png", 3))
    assert report.best_ref == 1
    assert report.score == report.per_ref[1]
    assert report.per_ref[0] == pytest.approx(0.1 / (0.82**0.5), abs=1e-4)
    assert report.refs_used == 2


def test_largest_face_is_the_one_compared(tmp_path):
    small, large = face_row(5, 5, 20, 20), face_row(40, 40, 60, 60)
    detector = FakeDetector({1: [small, large]})
    recognizer = FakeRecognizer({1: [1, 0, 0, 0]})
    gate = FaceGate(tmp_path, detector=detector, recognizer=recognizer)
    image = write_png(tmp_path / "pair.png", 1, size=128)
    assert [face.box[2] for face in gate.faces(image)] == [60, 20]
    report = gate.check([image], image)
    assert (report.faces_in_candidate, report.candidate_box) == (2, (40, 40, 60, 60))
    assert set(recognizer.widths) == {60}


def test_a_small_candidate_face_is_embedded_from_an_enlarged_crop(tmp_path):
    detector = FakeDetector({1: [face_row(8, 8, 20, 20)]})
    recognizer = FakeRecognizer({1: [1, 0, 0, 0]})
    gate = FaceGate(tmp_path, detector=detector, recognizer=recognizer)
    image = write_png(tmp_path / "small.png", 1, size=64)
    report = gate.check([image], image)
    assert report.status == "pass"
    assert report.enlarged == 4.0
    assert report.face_px == 20
    assert report.candidate_box == (8, 8, 20, 20)  # still in original coordinates
    assert any(h > 64 or w > 64 for h, w in detector.seen)


def test_a_face_at_the_small_face_boundary_is_not_enlarged(tmp_path):
    detector = FakeDetector({1: [face_row(20, 20, 120, 120)]})
    recognizer = FakeRecognizer({1: [1, 0, 0, 0]})
    gate = FaceGate(tmp_path, detector=detector, recognizer=recognizer)
    image = write_png(tmp_path / "big.png", 1, size=256)
    report = gate.check([image], image)
    assert report.enlarged is None
    assert report.face_px == 120


def test_enlarge_false_keeps_a_small_face_at_its_original_size(tmp_path):
    detector = FakeDetector({1: [face_row(8, 8, 20, 20)]})
    recognizer = FakeRecognizer({1: [1, 0, 0, 0]})
    gate = FaceGate(tmp_path, detector=detector, recognizer=recognizer, enlarge=False)
    image = write_png(tmp_path / "small.png", 1, size=64)
    report = gate.check([image], image)
    assert report.enlarged is None
    assert report.face_px == 20


def test_report_to_dict_carries_face_size_and_enlargement(tmp_path):
    detector = FakeDetector({1: [face_row(8, 8, 20, 20)]})
    gate = FaceGate(tmp_path, detector=detector, recognizer=FakeRecognizer({1: [1, 0, 0, 0]}))
    image = write_png(tmp_path / "small.png", 1, size=64)
    data = gate.check([image], image).to_dict()
    assert (data["face_px"], data["enlarged"]) == (20, 4.0)


def test_faceless_candidate_is_not_applicable(rig):
    report = rig.gate.check([rig.image("a.png", 1)], rig.image("sky.png", 9))
    assert report.status == "n/a"
    assert report.score is None
    assert report.best_ref is None
    assert (report.faces_in_candidate, report.candidate_box) == (0, None)
    assert "no face" in report.reason


@pytest.mark.parametrize("kind", ["missing", "not-an-image", "empty", "bad-array"])
def test_unreadable_candidate_is_not_applicable(rig, kind):
    candidate = {
        "missing": rig.folder / "nope.png",
        "not-an-image": rig.folder / "notes.txt",
        "empty": rig.folder / "empty.png",
        "bad-array": np.zeros((8, 8, 3), dtype=np.float32),
    }[kind]
    if kind == "not-an-image":
        candidate.write_bytes(b"definitely not an image")
    if kind == "empty":
        candidate.write_bytes(b"")
    report = rig.gate.check([rig.image("a.png", 1)], candidate)
    assert report.status == "n/a"
    assert report.score is None
    assert "candidate unreadable" in report.reason


def test_references_without_faces_are_skipped_and_counted(rig):
    refs = [rig.image("a.png", 1), rig.image("none.png", 9), rig.folder / "gone.png"]
    report = rig.gate.check(refs, rig.image("c.png", 3))
    assert report.status == "pass"
    assert report.per_ref[0] is not None
    assert report.per_ref[1:] == (None, None)
    assert (report.refs_used, report.best_ref) == (1, 0)


def test_no_usable_reference_is_not_applicable(rig):
    refs = [rig.image("none.png", 9), rig.folder / "gone.png"]
    report = rig.gate.check(refs, rig.image("c.png", 3))
    assert report.status == "n/a"
    assert report.score is None
    assert report.per_ref == (None, None)
    assert report.refs_used == 0
    assert report.faces_in_candidate == 1
    assert "reference" in report.reason


@pytest.mark.parametrize("references", [[], None])
def test_no_references_is_not_applicable(rig, references):
    report = rig.gate.check(references, rig.image("c.png", 3))
    assert (report.status, report.reason) == ("n/a", "no reference images given")


def test_a_bare_path_is_one_reference_not_a_list_of_characters(rig):
    report = rig.gate.check(str(rig.image("a.png", 1)), rig.image("c.png", 3))
    assert (report.status, len(report.per_ref)) == ("pass", 1)


def test_candidate_may_be_an_array(rig):
    report = rig.gate.check([rig.image("a.png", 1)], np.full((32, 32, 3), 3, dtype=np.uint8))
    assert report.status == "pass"


# --- unavailable models -----------------------------------------------------------------


def test_missing_models_are_unavailable_and_never_pass(tmp_path):
    same = write_png(tmp_path / "same.png", 5)
    gate = FaceGate(tmp_path / "no-models")
    assert gate.available is False
    assert "missing" in gate.reason
    assert "--download" in gate.reason
    report = gate.check([same], same)
    assert report.status == "unavailable"
    assert report.score is None
    assert report.best_ref is None
    assert report.reason == gate.reason
    assert gate.faces(same) == []
    assert gate.embed(same) is None
    assert gate.status()["available"] is False


def test_lfs_pointer_models_are_unavailable(tmp_path):
    (tmp_path / DETECTOR_FILE).write_bytes(LFS_POINTER)
    gate = FaceGate(tmp_path)
    assert gate.available is False
    assert "Git-LFS" in gate.reason


@pytest.mark.parametrize(("folder", "expects_hint"), [("face", False), ("caf\u00e9", True)])
def test_unloadable_models_are_unavailable(tmp_path, folder, expects_hint):
    models = tmp_path / folder
    models.mkdir()
    (models / DETECTOR_FILE).write_bytes(b"not an onnx file" * 12_500)
    gate = FaceGate(models)
    assert gate.available is False
    assert gate.reason.startswith("face models unavailable")
    assert ("OPENFIELD_MODEL_DIR" in gate.reason) is expects_hint
    assert gate.check([tmp_path], tmp_path).status == "unavailable"


def test_an_opencv_build_without_the_face_api_is_unavailable(tmp_path, monkeypatch):
    (tmp_path / DETECTOR_FILE).write_bytes(b"x" * MODELS["detector"].min_bytes)
    monkeypatch.delattr(identity.cv2, "FaceDetectorYN")
    gate = FaceGate(tmp_path)
    assert gate.available is False
    assert "FaceDetectorYN" in gate.reason


def test_a_failing_detector_is_unavailable_not_a_verdict(tmp_path):
    class Broken(FakeDetector):
        def detect(self, image):
            raise RuntimeError("detector exploded")

    gate = FaceGate(tmp_path, detector=Broken(), recognizer=FakeRecognizer({}))
    image = write_png(tmp_path / "x.png", 1)
    report = gate.check([image], image)
    assert report.status == "unavailable"
    assert report.score is None
    assert "detector exploded" in report.reason
    assert gate.faces(image) == []
    assert gate.embed(image) is None


# --- detection geometry -----------------------------------------------------------------


def test_boxes_are_mapped_back_from_a_downscaled_detection(tmp_path):
    detector = FakeDetector({0: [face_row(100, 50, 300, 200, score=0.8)]})
    gate = FaceGate(tmp_path, detector=detector, recognizer=FakeRecognizer({}))
    wide = np.zeros((2048, 4096, 3), dtype=np.uint8)
    [face] = gate.faces(wide)
    assert detector.sizes == [(2048, 1024)]
    assert detector.seen == [(1024, 2048)]
    assert face.box == (200, 100, 600, 400)
    assert face.score == pytest.approx(0.8)
    assert len(face.landmarks) == 5
    assert face.landmarks[0] == pytest.approx((380.0, 240.0))


def test_small_images_are_detected_at_full_size(tmp_path):
    detector = FakeDetector({0: [face_row(10, 20, 50, 60)]})
    gate = FaceGate(tmp_path, detector=detector, recognizer=FakeRecognizer({}))
    [face] = gate.faces(np.zeros((300, 400, 3), dtype=np.uint8))
    assert detector.sizes == [(400, 300)]
    assert face.box == (10, 20, 50, 60)


def test_boxes_are_clipped_to_the_image(tmp_path):
    detector = FakeDetector({0: [face_row(-10, 20, 50, 400)]})
    gate = FaceGate(tmp_path, detector=detector, recognizer=FakeRecognizer({}))
    [face] = gate.faces(np.zeros((100, 200, 3), dtype=np.uint8))
    assert face.box == (0, 20, 40, 80)


def test_a_close_up_missed_at_full_size_is_found_after_shrinking(tmp_path):
    class ScaleSensitive(FakeDetector):
        """Like YuNet: only finds the face once the whole frame is small enough."""

        def detect(self, image):
            self.seen.append(image.shape[:2])
            small_enough = max(image.shape[:2]) <= 960
            return (1, np.array([face_row(10, 10, 100, 100)], dtype=np.float32)) if small_enough else (1, None)

    detector = ScaleSensitive()
    gate = FaceGate(tmp_path, detector=detector, recognizer=FakeRecognizer({}))
    [face] = gate.faces(np.zeros((1500, 1500, 3), dtype=np.uint8))
    assert detector.seen == [(1500, 1500), (960, 960)]
    assert face.box == (16, 16, 156, 156)  # mapped back by 1500 / 960


def test_a_faceless_frame_is_tried_at_each_scale_once(tmp_path):
    detector = FakeDetector({})
    gate = FaceGate(tmp_path, detector=detector, recognizer=FakeRecognizer({}))
    assert gate.faces(np.zeros((1500, 1500, 3), dtype=np.uint8)) == []
    assert detector.seen == [(1500, 1500), (960, 960), (480, 480)]
    detector.seen.clear()
    gate.faces(np.zeros((300, 400, 3), dtype=np.uint8))
    assert detector.seen == [(300, 400)]  # small frames are not re-tried at identical sizes


@pytest.mark.parametrize("shape", [(64, 64), (64, 64, 3), (64, 64, 4)])
def test_faces_accepts_common_array_layouts(rig, shape):
    assert len(rig.gate.faces(np.full(shape, 1, dtype=np.uint8))) == 1


@pytest.mark.parametrize(
    "array", [np.full((64, 64, 3), 1, dtype=np.float32), np.zeros((0, 64, 3), dtype=np.uint8)]
)
def test_faces_rejects_unusable_arrays(rig, array):
    assert rig.gate.faces(array) == []


# --- embeddings and cache ---------------------------------------------------------------


def test_embed_returns_a_private_flat_float32_vector(rig):
    image = rig.image("a.png", 1)
    [face] = rig.gate.faces(image)
    embedding = rig.gate.embed(image)
    assert embedding.shape == (4,)
    assert embedding.dtype == np.float32
    assert np.array_equal(embedding, rig.gate.embed(image, face))
    embedding[:] = 0
    assert rig.gate.embed(image)[0] == 1.0


def test_embed_is_none_without_a_face_or_with_too_few_landmarks(rig):
    assert rig.gate.embed(rig.image("sky.png", 9)) is None
    assert rig.gate.embed(rig.image("a.png", 1), Face((0, 0, 8, 8), 0.9, ())) is None


def test_reference_embeddings_are_cached_until_the_file_changes(rig):
    ref, candidate = rig.image("a.png", 1), rig.image("c.png", 3)
    rig.gate.check([ref], candidate)
    assert rig.recognizer.feature_calls == 2
    rig.gate.check([ref], candidate)
    assert rig.recognizer.feature_calls == 3
    assert rig.gate.status()["cached_refs"] == 1

    write_png(ref, 2)
    later = ref.stat().st_mtime_ns + 5_000_000_000
    os.utime(ref, ns=(later, later))
    report = rig.gate.check([ref], candidate)
    assert rig.recognizer.feature_calls == 5
    assert report.score == pytest.approx(0.1 / (0.82**0.5), abs=1e-4)
    rig.gate.check([ref], candidate)
    assert rig.recognizer.feature_calls == 6


def test_references_without_faces_are_cached_too(rig):
    refs = [rig.image("a.png", 1), rig.image("none.png", 9)]
    candidate = rig.image("c.png", 3)
    rig.gate.check(refs, candidate)
    detections = len(rig.detector.seen)
    rig.gate.check(refs, candidate)
    # the cached references are not re-detected, but the small candidate face is: original + crop
    assert len(rig.detector.seen) == detections + 2


# --- report -----------------------------------------------------------------------------


def test_report_to_dict_is_plain_json(rig):
    refs = [rig.image("a.png", 1), rig.image("none.png", 9)]
    data = rig.gate.check(refs, rig.image("c.png", 3)).to_dict()
    assert json.loads(json.dumps(data)) == data
    assert data["status"] == "pass"
    assert isinstance(data["per_ref"], list)
    assert data["per_ref"][1] is None
    assert data["candidate_box"] == [8, 8, 40, 40]
    empty = rig.gate.check([], rig.image("c.png", 3)).to_dict()
    assert json.loads(json.dumps(empty)) == empty
    assert empty["candidate_box"] is None


def test_default_model_dir_honours_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENFIELD_MODEL_DIR", str(tmp_path))
    assert default_model_dir() == tmp_path / "face"
    monkeypatch.delenv("OPENFIELD_MODEL_DIR")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert default_model_dir() == tmp_path / ".cache" / "openfield" / "models" / "face"


def test_default_model_dir_avoids_a_non_ascii_home(monkeypatch, tmp_path):
    """OpenCV's ONNX loader cannot open non-ASCII paths on Windows."""
    monkeypatch.delenv("OPENFIELD_MODEL_DIR", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "José")
    monkeypatch.setenv("PUBLIC", str(tmp_path / "public"))
    assert default_model_dir() == tmp_path / "public" / "openfield" / "models" / "face"
    monkeypatch.delenv("PUBLIC")
    monkeypatch.delenv("ProgramData", raising=False)
    assert "José" in str(default_model_dir())  # nothing better exists: the hint explains it


# --- model pins and download ------------------------------------------------------------


def test_pins_point_at_the_lfs_media_endpoint():
    zoo = "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models"
    assert MODELS["detector"].url == f"{zoo}/face_detection_yunet/face_detection_yunet_2023mar.onnx"
    assert (
        MODELS["recognizer"].url
        == f"{zoo}/face_recognition_sface/face_recognition_sface_2021dec.onnx"
    )
    for spec in MODELS.values():
        assert spec.url.endswith("/" + spec.file)
        assert spec.min_bytes > len(LFS_POINTER)
        assert spec.sha256 is not None
        assert len(spec.sha256) == 64


@pytest.fixture
def specs(monkeypatch) -> dict[str, ModelSpec]:
    table = {
        role: ModelSpec(
            file=f"{role}.onnx",
            url=f"https://models.test/{role}.onnx",
            sha256=hashlib.sha256(blob).hexdigest(),
            min_bytes=1000,
        )
        for role, blob in PAYLOADS.items()
    }
    monkeypatch.setattr(identity, "MODELS", table)
    return table


def names(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir())


def test_download_writes_verified_files_and_sends_no_credentials(tmp_path, respx_mock, specs):
    routes = [
        respx_mock.get(spec.url).respond(content=PAYLOADS[role]) for role, spec in specs.items()
    ]
    dest = tmp_path / "models" / "face"
    paths = download_models(dest)
    assert paths == [dest / "detector.onnx", dest / "recognizer.onnx"]
    assert [p.read_bytes() for p in paths] == list(PAYLOADS.values())
    assert names(dest) == ["detector.onnx", "recognizer.onnx"]
    for route in routes:
        assert route.call_count == 1
        sent = {name.lower() for name in route.calls.last.request.headers}
        assert not sent & {"authorization", "cookie", "proxy-authorization"}


@pytest.mark.parametrize("stale", [LFS_POINTER, b"stale-weights-" * 100])
def test_download_skips_valid_files_and_replaces_invalid_ones(tmp_path, respx_mock, specs, stale):
    (tmp_path / "detector.onnx").write_bytes(PAYLOADS["detector"])
    (tmp_path / "recognizer.onnx").write_bytes(stale)
    detector = respx_mock.get(specs["detector"].url).respond(content=PAYLOADS["detector"])
    recognizer = respx_mock.get(specs["recognizer"].url).respond(content=PAYLOADS["recognizer"])
    download_models(tmp_path)
    assert (detector.call_count, recognizer.call_count) == (0, 1)
    assert (tmp_path / "recognizer.onnx").read_bytes() == PAYLOADS["recognizer"]
    download_models(tmp_path)
    assert recognizer.call_count == 1


def test_download_rejects_an_lfs_pointer_response(tmp_path, respx_mock, specs):
    respx_mock.get(specs["detector"].url).respond(content=LFS_POINTER)
    with pytest.raises(ModelDownloadError, match="Git-LFS"):
        download_models(tmp_path)
    assert names(tmp_path) == []


def test_download_rejects_a_wrong_sha256(tmp_path, respx_mock, specs):
    respx_mock.get(specs["detector"].url).respond(content=b"tampered!" * 500)
    with pytest.raises(ModelDownloadError, match="sha256"):
        download_models(tmp_path)
    assert names(tmp_path) == []


def test_download_reports_http_errors(tmp_path, respx_mock, specs):
    respx_mock.get(specs["detector"].url).respond(404)
    with pytest.raises(ModelDownloadError, match="404"):
        download_models(tmp_path)
    assert names(tmp_path) == []


def test_download_follows_redirects_even_with_a_stock_client(tmp_path, respx_mock, specs):
    blob = "https://cdn.test/blob/1"
    respx_mock.get(specs["detector"].url).respond(302, headers={"Location": blob})
    landed = respx_mock.get(blob).respond(content=PAYLOADS["detector"])
    respx_mock.get(specs["recognizer"].url).respond(content=PAYLOADS["recognizer"])
    with httpx.Client() as client:
        paths = download_models(tmp_path, client=client)
    assert paths[0].read_bytes() == PAYLOADS["detector"]
    assert "authorization" not in landed.calls.last.request.headers


class WatchedStream(httpx.SyncByteStream):
    """Serves a payload in two chunks and records the folder's contents in between."""

    def __init__(self, folder: Path, payload: bytes, *, die: bool) -> None:
        self.folder, self.payload, self.die = folder, payload, die
        self.midway: list[str] = []

    def __iter__(self):
        half = len(self.payload) // 2
        yield self.payload[:half]
        self.midway = names(self.folder)
        if self.die:
            raise httpx.ReadError("connection reset")
        yield self.payload[half:]


def test_download_streams_into_a_part_file_and_renames_it(tmp_path, respx_mock, specs):
    stream = WatchedStream(tmp_path, PAYLOADS["detector"], die=False)
    respx_mock.get(specs["detector"].url).mock(return_value=httpx.Response(200, stream=stream))
    respx_mock.get(specs["recognizer"].url).respond(content=PAYLOADS["recognizer"])
    download_models(tmp_path)
    assert stream.midway == ["detector.onnx.part"]
    assert names(tmp_path) == ["detector.onnx", "recognizer.onnx"]


def test_download_removes_the_part_file_when_the_transfer_dies(tmp_path, respx_mock, specs):
    stream = WatchedStream(tmp_path, PAYLOADS["detector"], die=True)
    respx_mock.get(specs["detector"].url).mock(return_value=httpx.Response(200, stream=stream))
    with pytest.raises(ModelDownloadError, match="connection reset"):
        download_models(tmp_path)
    assert stream.midway == ["detector.onnx.part"]
    assert names(tmp_path) == []


# --- command line -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("candidate_code", "exit_code", "status"), [(3, 0, "pass"), (4, 1, "drift"), (9, 2, "n/a")]
)
def test_cli_exit_status_follows_the_report(
    rig, monkeypatch, capsys, candidate_code, exit_code, status
):
    monkeypatch.setattr(identity, "FaceGate", lambda: rig.gate)
    ref, candidate = rig.image("a.png", 1), rig.image("cand.png", candidate_code)
    assert main([str(ref), "--", str(candidate), "--json"]) == exit_code
    assert json.loads(capsys.readouterr().out)["status"] == status


def test_cli_prints_a_one_line_summary_without_json(rig, monkeypatch, capsys):
    monkeypatch.setattr(identity, "FaceGate", lambda: rig.gate)
    ref, candidate = rig.image("a.png", 1), rig.image("cand.png", 3)
    assert main([str(ref), str(candidate)]) == 0
    assert capsys.readouterr().out.startswith("pass: cosine ")


def test_cli_reports_unavailable_models_with_status_two(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OPENFIELD_MODEL_DIR", str(tmp_path))
    image = write_png(tmp_path / "x.png", 1)
    assert main([str(image), "--", str(image)]) == 2
    assert capsys.readouterr().out.startswith("unavailable: ")


def test_cli_usage_errors_exit_two(capsys):
    assert main([]) == 2
    assert main(["lonely.png"]) == 2
    assert main(["a.png", "--"]) == 2
    assert "usage:" in capsys.readouterr().err


def test_cli_download_flag_fetches_models_and_stops_on_failure(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(identity, "download_models", lambda: [tmp_path / "m.onnx"])
    assert main(["--download"]) == 0
    assert "model ready" in capsys.readouterr().err

    def offline():
        raise ModelDownloadError("offline")

    monkeypatch.setattr(identity, "download_models", offline)
    assert main(["--download"]) == 2
    assert "offline" in capsys.readouterr().err


# --- live models (opt-in) ---------------------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("OPENFIELD_LIVE_FACE"),
    reason="set OPENFIELD_LIVE_FACE=1 with the models in default_model_dir() to run",
)
def test_live_models_load_and_a_blank_image_has_no_face(tmp_path):
    gate = FaceGate()
    assert gate.available, gate.reason
    blank = tmp_path / "blank.png"
    Image.fromarray(np.full((256, 256, 3), 127, dtype=np.uint8)).save(blank)
    assert gate.faces(blank) == []
    assert gate.check([blank], blank).status == "n/a"


def test_calls_from_different_threads_never_overlap_inside_the_detector(rig):
    """A cast upload and a take's identity check share one gate: the stateful OpenCV models must be serialised."""
    import threading
    import time

    state = {"active": 0, "peak": 0}
    guard = threading.Lock()
    original = rig.detector.detect

    def slow_detect(image):
        with guard:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        time.sleep(0.02)
        try:
            return original(image)
        finally:
            with guard:
                state["active"] -= 1

    rig.detector.detect = slow_detect
    image = rig.image("a.png", 1)
    reference = rig.image("ref.png", 1)
    results: list[object] = []
    work = [lambda: results.append(rig.gate.faces(image)), lambda: results.append(rig.gate.check([reference], image)),
            lambda: results.append(rig.gate.embed(image))]
    threads = [threading.Thread(target=work[i % 3]) for i in range(9)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(results) == 9 and state["peak"] == 1
