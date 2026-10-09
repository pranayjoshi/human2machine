from __future__ import annotations

from types import SimpleNamespace

import numpy as np
from audio_adapter.capture import describe_asr
from audio_adapter.parser import build_vocabulary, parse_utterance
from vision_adapter.camera import VisionHardwareRuntime
from vision_adapter.mediapipe_tasks import TasksFace, TasksHands
from vision_adapter.open_vocab import OpenVocabDetector, create_detector, prompt_for
from vision_adapter.pointing import try_mediapipe_pointing

CATALOG = [
    {"object_id": "obj_mug", "class_name": "mug", "prompt": "red mug"},
    {"object_id": "obj_remote", "class_name": "remote", "prompt": "tv remote"},
    {"object_id": "obj_block", "class_name": "red_block", "prompt": "red block"},
]


def test_vocabulary_maps_prompts_and_unique_words() -> None:
    vocab = build_vocabulary(CATALOG)
    assert vocab["red mug"] == "obj_mug"
    assert vocab["mug"] == "obj_mug"
    assert vocab["remote"] == "obj_remote"
    assert "red" not in vocab  # shared by two objects


def test_parser_uses_vocabulary_longest_match_first() -> None:
    vocab = build_vocabulary(CATALOG)
    assert parse_utterance("hand me the mug", vocabulary=vocab).target_object_id == "obj_mug"
    assert parse_utterance("pass the red block", vocabulary=vocab).target_object_id == "obj_block"
    ambiguous = parse_utterance("give me the red one", vocabulary=vocab)
    assert ambiguous.target_object_id is None


def test_parser_without_vocabulary_keeps_color_defaults() -> None:
    assert parse_utterance("give me the blue block").target_object_id == "object_blue_1"


def test_describe_parakeet_backend() -> None:
    def _parakeet(audio, sample_rate_hz):  # noqa: ANN001, ARG001
        return None

    assert describe_asr(_parakeet) == "parakeet-mlx"


def test_prompt_falls_back_to_class_name() -> None:
    assert prompt_for({"object_id": "x", "class_name": "green_cup"}) == "green cup"


def test_create_detector_respects_config() -> None:
    assert create_detector(CATALOG, {"detector": "hsv"}) is None


class _Tensor:
    def __init__(self, data) -> None:  # noqa: ANN001
        self._data = np.asarray(data)

    def cpu(self) -> _Tensor:
        return self

    def numpy(self):  # noqa: ANN201
        return self._data


class _Boxes:
    def __init__(self, xyxy, conf, cls) -> None:  # noqa: ANN001
        self.xyxy = _Tensor(xyxy)
        self.conf = _Tensor(conf)
        self.cls = _Tensor(cls)

    def __len__(self) -> int:
        return len(self.conf.numpy())


class _FakeModel:
    def __init__(self, boxes: _Boxes) -> None:
        self._boxes = boxes

    def predict(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN201
        return [SimpleNamespace(boxes=self._boxes)]


def _detector_with(boxes: _Boxes) -> OpenVocabDetector:
    detector = OpenVocabDetector.__new__(OpenVocabDetector)
    detector.catalog = [dict(item) for item in CATALOG]
    detector.prompts = [prompt_for(item) for item in CATALOG]
    detector.min_confidence = 0.25
    detector.imgsz = 640
    detector.device = "cpu"
    detector.model = _FakeModel(boxes)
    detector.model_id = "fake"
    return detector


def test_open_vocab_keeps_best_box_per_prompt() -> None:
    boxes = _Boxes(
        xyxy=[[0, 0, 100, 100], [10, 10, 50, 50], [200, 100, 300, 200]],
        conf=[0.4, 0.8, 0.6],
        cls=[0, 0, 1],
    )
    found = {
        row["object_id"]: row
        for row in _detector_with(boxes).detect(np.zeros((400, 400, 3), np.uint8))
    }
    assert set(found) == {"obj_mug", "obj_remote"}
    assert found["obj_mug"]["confidence"] == 0.8
    assert found["obj_mug"]["bbox_xyxy"] == [10.0, 10.0, 50.0, 50.0]
    assert found["obj_remote"]["table_position_xy"] == [0.625, 0.375]


def test_hardware_runtime_uses_injected_detector() -> None:
    frame = np.zeros((720, 1280, 3), np.uint8)
    camera = SimpleNamespace(latest=lambda: (frame, 1_000, 1_000))
    detector = SimpleNamespace(
        model_id="yoloe-test",
        detect=lambda _frame: [
            {
                "object_id": "obj_mug",
                "class_name": "mug",
                "confidence": 0.9,
                "bbox_xyxy": [10.0, 10.0, 50.0, 50.0],
                "table_position_xy": [0.1, 0.1],
            }
        ],
    )
    runtime = VisionHardwareRuntime(
        camera, catalog=CATALOG, hands=None, face=None, detector=detector
    )
    events = runtime.render_frame(monotonic_ns=1_000)
    objects = next(e for e in events if str(e.event_type) == "vision.objects").payload["objects"]
    assert [row["object_id"] for row in objects] == ["obj_mug"]
    status = next(e for e in events if str(e.event_type) == "device.status")
    assert status.payload["metadata"]["detector"] == "yoloe-test"


def _point(x: float, y: float) -> SimpleNamespace:
    return SimpleNamespace(x=x, y=y, z=0.0)


def test_tasks_hands_matches_legacy_shape() -> None:
    hand = [_point(0.5, 0.5) for _ in range(21)]
    hand[5] = _point(0.5, 0.6)  # index MCP
    hand[8] = _point(0.5, 0.4)  # index tip
    landmarker = SimpleNamespace(
        detect_for_video=lambda _image, _ts: SimpleNamespace(
            hand_landmarks=[hand],
            handedness=[[SimpleNamespace(score=0.93, category_name="Right")]],
        ),
        close=lambda: None,
    )
    hands = TasksHands(landmarker)
    _candidates, payload = try_mediapipe_pointing(
        np.zeros((480, 640, 3), np.uint8), [], 0.55, hands
    )
    assert payload["handedness"] == "right"
    assert payload["landmark_confidence"] == 0.93


def test_tasks_face_returns_none_without_faces() -> None:
    landmarker = SimpleNamespace(
        detect_for_video=lambda _image, _ts: SimpleNamespace(face_landmarks=[]),
        close=lambda: None,
    )
    result = TasksFace(landmarker).process(np.zeros((10, 10, 3), np.uint8))
    assert result.multi_face_landmarks is None
