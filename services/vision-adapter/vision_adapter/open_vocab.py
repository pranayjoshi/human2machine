"""Text-prompted open-vocabulary object detection with Ultralytics YOLOE-26.

Each catalog entry is matched by a natural-language ``prompt`` (for example
"red mug" or "tv remote"), so the tabletop no longer needs color-coded blocks.
The best-scoring box per prompt becomes that object's detection; output rows
match ``detect_colored_objects`` so the tracker and fusion are unchanged.

Prompt embeddings are cached next to the weights so the CLIP text encoder only
downloads once.
"""

from __future__ import annotations

import contextlib
import hashlib
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from vision_adapter.mediapipe_tasks import models_dir

DEFAULT_MODEL = "yoloe-26s-seg.pt"
DEFAULT_MIN_CONFIDENCE = 0.25


def prompt_for(item: dict[str, Any]) -> str:
    prompt = item.get("prompt")
    if prompt:
        return str(prompt)
    return str(item.get("class_name") or item["object_id"]).replace("_", " ")


def _pick_device() -> str:
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


class OpenVocabDetector:
    name = "yoloe"

    def __init__(
        self,
        catalog: list[dict[str, Any]],
        *,
        model_name: str = DEFAULT_MODEL,
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
        imgsz: int = 640,
        device: str | None = None,
        directory: Path | None = None,
    ) -> None:
        from ultralytics import YOLOE

        self.catalog = [dict(item) for item in catalog]
        self.prompts = [prompt_for(item) for item in self.catalog]
        self.min_confidence = float(min_confidence)
        self.imgsz = int(imgsz)
        self.device = device or _pick_device()
        directory = directory or models_dir()
        directory.mkdir(parents=True, exist_ok=True)
        weights = directory / model_name
        self.model = YOLOE(str(weights) if weights.exists() else model_name)
        if not weights.exists():
            downloaded = Path(getattr(self.model, "ckpt_path", "") or "")
            if downloaded.is_file() and downloaded.resolve() != weights.resolve():
                downloaded.replace(weights)
        self._load_prompts(directory, model_name)
        # First MPS/CUDA inference compiles kernels (~5 s); do it before streaming.
        self.detect(np.zeros((self.imgsz, self.imgsz, 3), dtype=np.uint8))
        self.model_id = f"{Path(model_name).stem}:{len(self.prompts)}-prompts"

    def _load_prompts(self, directory: Path, model_name: str) -> None:
        key = hashlib.sha1("|".join([model_name, *self.prompts]).encode()).hexdigest()[:12]
        cache = directory / f"prompts-{key}.npz"
        if cache.exists() and hasattr(self.model, "load_prompt_embeddings"):
            try:
                self.model.load_prompt_embeddings(str(cache))
                return
            except Exception:
                pass
        # Ultralytics fetches the text encoder into the working directory.
        with contextlib.chdir(directory):
            self.model.set_classes(self.prompts)
        if hasattr(self.model, "save_prompt_embeddings"):
            try:
                self.model.save_prompt_embeddings(str(cache))
            except Exception:
                pass

    def detect(self, frame_bgr: NDArray[np.uint8]) -> list[dict[str, Any]]:
        results = self.model.predict(
            frame_bgr,
            conf=self.min_confidence,
            imgsz=self.imgsz,
            device=self.device,
            verbose=False,
        )
        if not results:
            return []
        boxes = results[0].boxes
        if boxes is None or len(boxes) == 0:
            return []
        xyxy = boxes.xyxy.cpu().numpy()
        confs = boxes.conf.cpu().numpy()
        classes = boxes.cls.cpu().numpy().astype(int)
        height, width = frame_bgr.shape[:2]
        best: dict[int, int] = {}
        for index, cls in enumerate(classes):
            if 0 <= cls < len(self.catalog) and (
                cls not in best or confs[index] > confs[best[cls]]
            ):
                best[cls] = index
        found: list[dict[str, Any]] = []
        for cls, index in best.items():
            item = self.catalog[cls]
            x1, y1, x2, y2 = (float(v) for v in xyxy[index])
            found.append(
                {
                    "object_id": item["object_id"],
                    "class_name": item.get("class_name", item["object_id"]),
                    "confidence": float(min(0.99, confs[index])),
                    "bbox_xyxy": [x1, y1, x2, y2],
                    "table_position_xy": [
                        (x1 + x2) / 2.0 / max(width, 1),
                        (y1 + y2) / 2.0 / max(height, 1),
                    ],
                }
            )
        return found


def create_detector(
    catalog: list[dict[str, Any]], vision_cfg: dict[str, Any]
) -> OpenVocabDetector | None:
    """Build the configured detector, or None to use HSV/ArUco detection."""
    if str(vision_cfg.get("detector", "hsv")).lower() != "yoloe":
        return None
    return OpenVocabDetector(
        catalog,
        model_name=str(vision_cfg.get("detector_model", DEFAULT_MODEL)),
        min_confidence=float(vision_cfg.get("detector_min_confidence", DEFAULT_MIN_CONFIDENCE)),
        imgsz=int(vision_cfg.get("detector_imgsz", 640)),
    )
