from __future__ import annotations

import math
from typing import Any

import numpy as np
from numpy.typing import NDArray

try:
    import cv2
except Exception:  # pragma: no cover - optional in some CI images
    cv2 = None  # type: ignore[assignment]

# MediaPipe Face Mesh indices used when the optional landmarker is present.
FACE_NOSE = 1
FACE_LEFT_EYE = 33
FACE_RIGHT_EYE = 263
FACE_CHIN = 152
FACE_FOREHEAD = 10
FACE_LEFT_EAR = 234
FACE_RIGHT_EAR = 454

# Head direction is supporting evidence only: broad cone, capped scores.
HEAD_SUPPORT_SCALE = 0.38
MAX_HEAD_CANDIDATE_CONFIDENCE = 0.40
CONE_RADIUS = 0.52
DEFAULT_HEAD_CONFIDENCE = 0.48


def empty_head_direction() -> dict[str, Any]:
    return {
        "yaw_deg": None,
        "pitch_deg": None,
        "confidence": 0.0,
        "candidates": [],
    }


def _xy(point: Any) -> tuple[float, float]:
    if hasattr(point, "x") and hasattr(point, "y"):
        return (float(point.x), float(point.y))
    return (float(point[0]), float(point[1]))


def _as_landmark_map(landmarks: Any) -> dict[str, tuple[float, float]]:
    if isinstance(landmarks, dict):
        return {str(key): _xy(value) for key, value in landmarks.items()}
    if isinstance(landmarks, (list, tuple)) and landmarks:
        first = landmarks[0]
        if hasattr(first, "x") or (isinstance(first, (list, tuple)) and len(first) >= 2):
            mapped = {}
            index_names = {
                FACE_NOSE: "nose",
                FACE_LEFT_EYE: "left_eye",
                FACE_RIGHT_EYE: "right_eye",
                FACE_CHIN: "chin",
                FACE_FOREHEAD: "forehead",
                FACE_LEFT_EAR: "left_ear",
                FACE_RIGHT_EAR: "right_ear",
            }
            if len(landmarks) > FACE_RIGHT_EAR:
                for index, name in index_names.items():
                    mapped[name] = _xy(landmarks[index])
                return mapped
            if len(landmarks) >= 3:
                return {
                    "nose": _xy(landmarks[0]),
                    "left_eye": _xy(landmarks[1]),
                    "right_eye": _xy(landmarks[2]),
                }
    raise ValueError("unsupported face landmark format")


def synthetic_face_landmarks(
    yaw_deg: float,
    pitch_deg: float,
    *,
    image_size: tuple[int, int] = (320, 240),
    face_center: tuple[float, float] | None = None,
) -> dict[str, tuple[float, float]]:
    """Build a coarse face in pixel coordinates from yaw/pitch.

    Positive yaw looks toward +x (right of the table image). Positive pitch
    looks downward onto the table (nose shifts toward +y).
    """
    width, height = image_size
    cx, cy = face_center if face_center is not None else (width * 0.50, height * 0.16)
    face_w = width * 0.16
    face_h = height * 0.18
    eye_span = face_w * 0.64
    eye_y = cy - face_h * 0.12
    face_height = face_h * 0.90
    # Offsets invert yaw_pitch_from_landmarks so tests can request a pose.
    yaw_shift = (yaw_deg / 70.0) * eye_span
    pitch_shift = (pitch_deg / 80.0) * face_height
    return {
        "left_eye": (cx - face_w * 0.32, eye_y),
        "right_eye": (cx + face_w * 0.32, eye_y),
        "nose": (cx + yaw_shift, eye_y + pitch_shift),
        "chin": (cx + yaw_shift * 0.25, cy + face_h * 0.48),
        "forehead": (cx, cy - face_h * 0.42),
        "left_ear": (cx - face_w * 0.58, cy + face_h * 0.02),
        "right_ear": (cx + face_w * 0.58, cy + face_h * 0.02),
    }


def yaw_pitch_from_landmarks(
    landmarks: Any,
    image_size: tuple[int, int] | None = None,
) -> tuple[float, float, float]:
    mapped = _as_landmark_map(landmarks)
    if "nose" not in mapped or "left_eye" not in mapped or "right_eye" not in mapped:
        return (0.0, 0.0, 0.0)
    nose = np.array(mapped["nose"], dtype=float)
    left_eye = np.array(mapped["left_eye"], dtype=float)
    right_eye = np.array(mapped["right_eye"], dtype=float)
    eye_mid = (left_eye + right_eye) / 2.0
    face_width = float(np.linalg.norm(right_eye - left_eye))
    if face_width < 1e-6:
        return (0.0, 0.0, 0.0)
    if image_size is not None and all(0.0 <= value <= 1.0 for value in (*nose, *left_eye, *right_eye)):
        width, height = image_size
        scale = np.array([max(width, 1), max(height, 1)], dtype=float)
        nose = nose * scale
        left_eye = left_eye * scale
        right_eye = right_eye * scale
        eye_mid = (left_eye + right_eye) / 2.0
        face_width = float(np.linalg.norm(right_eye - left_eye))
    yaw_deg = float(np.clip((nose[0] - eye_mid[0]) / face_width * 70.0, -60.0, 60.0))
    chin = mapped.get("chin")
    forehead = mapped.get("forehead")
    if chin is not None and forehead is not None:
        face_height = abs(chin[1] - forehead[1])
    else:
        face_height = face_width * 1.35
    if face_height < 1e-6:
        pitch_deg = 0.0
    else:
        pitch_deg = float(np.clip((nose[1] - eye_mid[1]) / face_height * 80.0, -45.0, 45.0))
    confidence = DEFAULT_HEAD_CONFIDENCE
    return yaw_deg, pitch_deg, confidence


def project_head_cone(
    yaw_deg: float,
    pitch_deg: float,
    objects: list[dict[str, Any]],
    *,
    confidence: float = DEFAULT_HEAD_CONFIDENCE,
    cone_radius: float = CONE_RADIUS,
) -> list[dict[str, Any]]:
    """Project a broad look cone onto table objects.

    Scores are intentionally weak so head direction cannot select a target
    by itself.
    """
    # Face is framed near the top of the table image. Negative yaw looks left;
    # modest positive pitch still covers nearer (upper) objects.
    look_x = float(np.clip(0.5 + math.sin(math.radians(yaw_deg)) * 0.50, 0.0, 1.0))
    look_y = float(np.clip(0.28 + math.sin(math.radians(pitch_deg)) * 0.22, 0.0, 1.0))
    look = np.array([look_x, look_y], dtype=float)
    candidates: list[dict[str, Any]] = []
    for obj in objects:
        pos = np.array(obj.get("table_position_xy") or [0.5, 0.5], dtype=float)
        dist = float(np.linalg.norm(pos - look))
        raw = max(0.0, 1.0 - dist / max(cone_radius, 1e-6))
        score = min(MAX_HEAD_CANDIDATE_CONFIDENCE, raw * float(confidence) * HEAD_SUPPORT_SCALE)
        if score >= 0.06:
            candidates.append({"object_id": obj["object_id"], "confidence": float(score)})
    candidates.sort(key=lambda row: row["confidence"], reverse=True)
    return candidates


def head_direction_from_landmarks(
    landmarks: Any,
    objects: list[dict[str, Any]],
    image_size: tuple[int, int] | None = None,
) -> dict[str, Any]:
    yaw_deg, pitch_deg, confidence = yaw_pitch_from_landmarks(landmarks, image_size)
    if confidence <= 0.0:
        return empty_head_direction()
    candidates = project_head_cone(yaw_deg, pitch_deg, objects, confidence=confidence)
    return {
        "yaw_deg": yaw_deg,
        "pitch_deg": pitch_deg,
        "confidence": confidence,
        "candidates": candidates,
    }


def head_direction_from_pose(
    yaw_deg: float,
    pitch_deg: float,
    objects: list[dict[str, Any]],
    *,
    confidence: float = DEFAULT_HEAD_CONFIDENCE,
) -> dict[str, Any]:
    return {
        "yaw_deg": float(yaw_deg),
        "pitch_deg": float(pitch_deg),
        "confidence": float(confidence),
        "candidates": project_head_cone(yaw_deg, pitch_deg, objects, confidence=confidence),
    }


def maybe_create_face_landmarker() -> Any | None:
    """Optional MediaPipe Face Mesh. Returns None when the package is missing."""
    try:
        import mediapipe as mp
    except Exception:
        return None
    try:
        return mp.solutions.face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=1,
            refine_landmarks=False,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
    except Exception:
        return None


def try_mediapipe_head_direction(
    frame_bgr: NDArray[np.uint8],
    objects: list[dict[str, Any]],
    landmarker: Any | None = None,
) -> dict[str, Any]:
    if landmarker is None or cv2 is None:
        return empty_head_direction()
    try:
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        result = landmarker.process(rgb)
    except Exception:
        return empty_head_direction()
    multi = getattr(result, "multi_face_landmarks", None)
    if not multi:
        return empty_head_direction()
    height, width = frame_bgr.shape[:2]
    face = multi[0].landmark
    landmarks = {
        "nose": (face[FACE_NOSE].x * width, face[FACE_NOSE].y * height),
        "left_eye": (face[FACE_LEFT_EYE].x * width, face[FACE_LEFT_EYE].y * height),
        "right_eye": (face[FACE_RIGHT_EYE].x * width, face[FACE_RIGHT_EYE].y * height),
        "chin": (face[FACE_CHIN].x * width, face[FACE_CHIN].y * height),
        "forehead": (face[FACE_FOREHEAD].x * width, face[FACE_FOREHEAD].y * height),
    }
    return head_direction_from_landmarks(landmarks, objects, (width, height))
