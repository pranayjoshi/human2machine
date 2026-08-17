from __future__ import annotations

from audio_adapter.mock import AudioMockRuntime
from crown_adapter.mock import CrownMockRuntime
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
    eeg_runtime = CrownMockRuntime(seed=1)
    eeg = []
    for _ in range(4):
        eeg.extend(eeg_runtime.tick())
    events = [*audio, *vision, *emg, *eeg]
    assert events
    for event in events:
        parsed = parse_unnormalized_event(event.to_unnormalized_dict())
        assert parsed.normalized_time_ns is None
