"""Download and warm every local model the hardware stack uses.

- MediaPipe hand/face landmarkers (pointing, head direction)
- YOLOE-26 weights + cached prompt embeddings for configs/modalities.yaml objects
- NVIDIA Parakeet TDT 0.6B v3 (MLX) speech recognition
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for rel in (
    "packages/contracts-python/src",
    "packages/runtime-python/src",
    "services/audio-adapter",
    "services/vision-adapter",
):
    sys.path.insert(0, str(ROOT / rel))

from intent_runtime.config import load_stacked_config  # noqa: E402
from vision_adapter.mediapipe_tasks import MODEL_URLS, models_dir  # noqa: E402


def main() -> int:
    target = models_dir()
    target.mkdir(parents=True, exist_ok=True)
    for name, url in MODEL_URLS.items():
        path = target / name
        if path.exists():
            print(f"ok   {name}")
            continue
        print(f"get  {name}")
        urllib.request.urlretrieve(url, path)

    config = load_stacked_config(ROOT / "configs")
    vision = config.get("vision", {})
    if str(vision.get("detector", "hsv")).lower() == "yoloe":
        from vision_adapter.open_vocab import create_detector

        detector = create_detector(list(vision.get("objects") or []), vision)
        print(f"ok   {detector.model_id} on {detector.device}")

    backend = str(config.get("audio", {}).get("asr_backend") or "parakeet")
    from audio_adapter.capture import describe_asr, resolve_asr

    asr = resolve_asr(backend)
    print(f"ok   asr {describe_asr(asr)}")
    return 0 if asr is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
