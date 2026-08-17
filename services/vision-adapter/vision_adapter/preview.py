"""Latest-frame JPEG preview for the operator UI. Not persisted into sessions."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]

PREVIEW_RELATIVE = Path("data/runtime/vision_preview.jpg")
META_RELATIVE = Path("data/runtime/vision_preview.json")
DEFAULT_MAX_WIDTH = 960
DEFAULT_JPEG_QUALITY = 55
STALE_AFTER_S = 2.5


def default_preview_path(repo_root: Path) -> Path:
    return repo_root / PREVIEW_RELATIVE


def default_meta_path(repo_root: Path) -> Path:
    return repo_root / META_RELATIVE


def encode_preview_jpeg(
    frame_bgr: NDArray[np.uint8],
    *,
    max_width: int = DEFAULT_MAX_WIDTH,
    quality: int = DEFAULT_JPEG_QUALITY,
) -> bytes:
    if cv2 is None:
        raise RuntimeError("opencv-python is required for camera preview")
    height, width = frame_bgr.shape[:2]
    scale = min(1.0, float(max_width) / max(width, 1))
    image = frame_bgr
    if scale < 1.0:
        image = cv2.resize(
            frame_bgr,
            (max(1, int(width * scale)), max(1, int(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    ok, buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        raise RuntimeError("failed to encode camera preview jpeg")
    return bytes(buffer)


def write_preview_jpeg(
    frame_bgr: NDArray[np.uint8],
    jpeg_path: Path,
    *,
    meta_path: Path | None = None,
    max_width: int = DEFAULT_MAX_WIDTH,
    quality: int = DEFAULT_JPEG_QUALITY,
) -> dict[str, Any]:
    jpeg_path.parent.mkdir(parents=True, exist_ok=True)
    payload = encode_preview_jpeg(frame_bgr, max_width=max_width, quality=quality)
    tmp = jpeg_path.with_suffix(".jpg.tmp")
    tmp.write_bytes(payload)
    tmp.replace(jpeg_path)
    height, width = frame_bgr.shape[:2]
    meta = {
        "width": int(width),
        "height": int(height),
        "updated_at_s": time.time(),
        "bytes": len(payload),
    }
    target_meta = meta_path or jpeg_path.with_suffix(".json")
    target_meta.parent.mkdir(parents=True, exist_ok=True)
    meta_tmp = target_meta.with_suffix(".json.tmp")
    meta_tmp.write_text(json.dumps(meta) + "\n")
    meta_tmp.replace(target_meta)
    return meta


def preview_status(jpeg_path: Path, *, stale_after_s: float = STALE_AFTER_S) -> dict[str, Any]:
    meta_path = jpeg_path.with_suffix(".json")
    exists = jpeg_path.exists()
    width, height = 1280, 720
    updated_at_s = jpeg_path.stat().st_mtime if exists else None
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
            width = int(meta.get("width") or width)
            height = int(meta.get("height") or height)
            updated_at_s = float(meta.get("updated_at_s") or updated_at_s or 0.0)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
    age_s = None if updated_at_s is None else max(0.0, time.time() - float(updated_at_s))
    available = bool(exists) and (age_s is None or age_s <= stale_after_s)
    return {
        "available": available,
        "width": width,
        "height": height,
        "age_s": None if age_s is None else round(age_s, 3),
    }
