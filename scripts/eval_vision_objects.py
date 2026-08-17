"""Synthetic four-object detection recall for Milestone 2.

Generates frames in-process. Does not open a camera or read video files.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages/contracts-python/src"))
sys.path.insert(0, str(ROOT / "packages/runtime-python/src"))
sys.path.insert(0, str(ROOT / "services/vision-adapter"))
sys.path.insert(0, str(ROOT))

from vision_adapter.color_detector import detect_colored_objects  # noqa: E402

from tests.helpers.vision_images import EXPECTED_IDS  # noqa: E402
from tests.end_to_end.test_milestone2_vision_objects import (  # noqa: E402
    RECALL_THRESHOLD,
    STATIONARY_FRAMES,
    _stationary_color_frame,
)


def main() -> int:
    hits = 0
    expected = 0
    for index in range(STATIONARY_FRAMES):
        found = {item["object_id"] for item in detect_colored_objects(_stationary_color_frame(index))}
        for object_id in EXPECTED_IDS:
            expected += 1
            if object_id in found:
                hits += 1
    recall = hits / max(expected, 1)
    print(f"frames={STATIONARY_FRAMES} expected={expected} hits={hits} recall={recall:.4f}")
    print(f"threshold={RECALL_THRESHOLD}")
    return 0 if recall >= RECALL_THRESHOLD else 1


if __name__ == "__main__":
    raise SystemExit(main())
