from __future__ import annotations

import time

import numpy as np
from ganglion_adapter.acquisition import GANGLION_BOARD_ID, BrainFlowAcquisition
from ganglion_adapter.main import main
from ganglion_adapter.publisher import ListSink


class FakeBoardShim:
    last_instance: FakeBoardShim | None = None

    def __init__(self, board_id: int, params) -> None:
        self.board_id = board_id
        self.params = params
        self.prepared = False
        self.streaming = False
        self.released = False
        self.stopped = False
        FakeBoardShim.last_instance = self

    def prepare_session(self) -> None:
        self.prepared = True

    def start_stream(self, *_args, **_kwargs) -> None:
        if not self.prepared:
            raise RuntimeError("prepare_session was not called")
        self.streaming = True

    def get_board_data(self) -> np.ndarray:
        if not self.streaming:
            return np.zeros((16, 0))
        n = 16
        data = np.zeros((16, n), dtype=float)
        data[1:5] = np.linspace(1.0, 4.0, 4).reshape(4, 1)
        data[13] = 1_700_000_000.0 + np.arange(n) / 200.0
        return data

    def stop_stream(self) -> None:
        self.streaming = False
        self.stopped = True

    def release_session(self) -> None:
        self.released = True
        self.prepared = False

    @staticmethod
    def get_eeg_channels(_board_id: int) -> list[int]:
        return [1, 2, 3, 4]

    @staticmethod
    def get_timestamp_channel(_board_id: int) -> int:
        return 13


def test_brainflow_start_stop_release_and_four_channels() -> None:
    acq = BrainFlowAcquisition(
        "/dev/cu.usbserial-TEST",
        board_shim=FakeBoardShim,
        board_id=GANGLION_BOARD_ID,
        eeg_channels=[1, 2, 3, 4],
        timestamp_channel=13,
        poll_s=0.01,
    )
    acq.start()
    try:
        chunk = None
        deadline = time.time() + 2.0
        while time.time() < deadline:
            chunk = acq.next_chunk()
            if chunk is not None:
                break
        assert chunk is not None
        samples, first_ns, label = chunk
        assert samples.shape[0] == 4
        assert samples.shape[1] > 0
        assert first_ns > 0
        assert label == "live"
        assert acq.last_receive_ns is not None
    finally:
        acq.stop()
    instance = FakeBoardShim.last_instance
    assert instance is not None
    assert instance.prepared is False or instance.released is True
    assert instance.stopped is True
    assert instance.released is True
    assert instance.streaming is False


def test_read_chunk_matches_next_chunk_shape() -> None:
    acq = BrainFlowAcquisition(
        "/dev/cu.usbserial-TEST",
        board_shim=FakeBoardShim,
        eeg_channels=[1, 2, 3, 4],
        timestamp_channel=13,
        poll_s=0.01,
    )
    acq.start()
    try:
        deadline = time.time() + 2.0
        chunk = None
        while time.time() < deadline:
            chunk = acq.read_chunk()
            if chunk is not None:
                break
        assert chunk is not None
        assert chunk[0].shape[0] == 4
    finally:
        acq.stop()


def test_hardware_start_failure_emits_offline_and_exits(monkeypatch) -> None:
    def boom(self) -> None:
        raise RuntimeError("dongle missing")

    monkeypatch.setattr(BrainFlowAcquisition, "start", boom)
    sink = ListSink()
    code = main(["--hardware", "--port", "/dev/cu.usbserial-FAKE"], sink=sink)
    assert code == 1
    statuses = [event for event in sink.events if event["event_type"] == "device.status"]
    assert statuses
    assert statuses[0]["payload"]["status"] == "offline"
    assert "dongle missing" in str(statuses[0]["payload"]["detail"])
    assert "normalized_time_ns" not in statuses[0]
