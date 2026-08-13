from __future__ import annotations

from audio_adapter.mock import AudioMockRuntime
from ganglion_adapter.mock import GanglionMockRuntime
from intent_contracts.validation import parse_unnormalized_event
from vision_adapter.mock import VisionMockRuntime


def test_every_python_adapter_mock_message_parses() -> None:
    audio = AudioMockRuntime().collect()
    vision = VisionMockRuntime(scenario="all_visible").render_frame(0)
    emg_runtime = GanglionMockRuntime(seed=1)
    emg = []
    for _ in range(8):
        emg.extend(emg_runtime.tick())
    events = [*audio, *vision, *emg]
    assert events
    for event in events:
        parsed = parse_unnormalized_event(event.to_unnormalized_dict())
        assert parsed.normalized_time_ns is None
