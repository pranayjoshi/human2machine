"""MediaPipe Tasks (>=0.10.30 / 1.x) landmarkers behind the legacy ``process()`` shape.

MediaPipe 1.x removed ``mp.solutions``. These wrappers run the Tasks
HandLandmarker / FaceLandmarker in VIDEO mode and return results shaped like the
legacy Hands / FaceMesh outputs, so ``try_mediapipe_pointing`` and
``try_mediapipe_head_direction`` stay unchanged.

Model files are the official ``.task`` bundles in ``models/vision/``.
"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
from numpy.typing import NDArray

HAND_MODEL = "hand_landmarker.task"
FACE_MODEL = "face_landmarker.task"
MODEL_URLS = {
    HAND_MODEL: "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task",
    FACE_MODEL: "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task",
}


def models_dir() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists():
            return parent / "models" / "vision"
    return Path("models/vision")


def _model_path(name: str, directory: Path | None) -> Path | None:
    path = (directory or models_dir()) / name
    return path if path.is_file() else None


class _VideoClock:
    """Tasks VIDEO mode requires strictly increasing millisecond timestamps."""

    def __init__(self) -> None:
        self._last_ms = -1

    def next_ms(self) -> int:
        now = time.monotonic_ns() // 1_000_000
        self._last_ms = max(now, self._last_ms + 1)
        return self._last_ms


def _image(rgb: NDArray[np.uint8]) -> Any:
    import mediapipe as mp

    return mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))


class TasksHands:
    def __init__(self, landmarker: Any) -> None:
        self._landmarker = landmarker
        self._clock = _VideoClock()

    def process(self, rgb: NDArray[np.uint8]) -> SimpleNamespace:
        result = self._landmarker.detect_for_video(_image(rgb), self._clock.next_ms())
        hands = [SimpleNamespace(landmark=list(points)) for points in result.hand_landmarks]
        handedness = [
            SimpleNamespace(
                classification=[
                    SimpleNamespace(score=float(cats[0].score), label=cats[0].category_name)
                ]
            )
            for cats in result.handedness
            if cats
        ]
        return SimpleNamespace(
            multi_hand_landmarks=hands or None,
            multi_handedness=handedness or None,
        )

    def close(self) -> None:
        self._landmarker.close()


class TasksFace:
    def __init__(self, landmarker: Any) -> None:
        self._landmarker = landmarker
        self._clock = _VideoClock()

    def process(self, rgb: NDArray[np.uint8]) -> SimpleNamespace:
        result = self._landmarker.detect_for_video(_image(rgb), self._clock.next_ms())
        faces = [SimpleNamespace(landmark=list(points)) for points in result.face_landmarks]
        return SimpleNamespace(multi_face_landmarks=faces or None)

    def close(self) -> None:
        self._landmarker.close()


def create_tasks_hands(directory: Path | None = None) -> TasksHands | None:
    path = _model_path(HAND_MODEL, directory)
    if path is None:
        return None
    try:
        from mediapipe.tasks.python import BaseOptions, vision

        options = vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(path)),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=1,
            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        return TasksHands(vision.HandLandmarker.create_from_options(options))
    except Exception:
        return None


def create_tasks_face(directory: Path | None = None) -> TasksFace | None:
    path = _model_path(FACE_MODEL, directory)
    if path is None:
        return None
    try:
        from mediapipe.tasks.python import BaseOptions, vision

        options = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(path)),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=1,
            min_face_detection_confidence=0.5,
            min_face_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        return TasksFace(vision.FaceLandmarker.create_from_options(options))
    except Exception:
        return None
