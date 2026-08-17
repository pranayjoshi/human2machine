from __future__ import annotations

import time

import numpy as np
from ganglion_adapter.acquisition import (
    GANGLION_BOARD_ID,
    GANGLION_NATIVE_BOARD_ID,
    BrainFlowAcquisition,
    connection_from_mapping,
)
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


def test_usb_hardware_without_port_exits_offline() -> None:
    sink = ListSink()
    code = main(["--hardware", "--transport", "usb_dongle"], sink=sink)
    assert code == 1
    statuses = [event for event in sink.events if event["event_type"] == "device.status"]
    assert statuses
    assert statuses[0]["payload"]["status"] == "offline"
    assert "serial_port" in str(statuses[0]["payload"]["detail"])


def test_ble_start_uses_native_board_and_optional_mac() -> None:
    acq = BrainFlowAcquisition(
        transport="ble",
        mac_address="AA:BB:CC:DD:EE:FF",
        board_shim=FakeBoardShim,
        eeg_channels=[1, 2, 3, 4],
        timestamp_channel=13,
        poll_s=0.01,
    )
    acq.start()
    try:
        instance = FakeBoardShim.last_instance
        assert instance is not None
        assert instance.board_id == GANGLION_NATIVE_BOARD_ID
        assert instance.params.mac_address == "AA:BB:CC:DD:EE:FF"
        assert instance.params.timeout == 15
        assert instance.prepared is True
    finally:
        acq.stop()


def test_ble_autodiscover_does_not_require_serial_port() -> None:
    acq = BrainFlowAcquisition(
        transport="ble",
        board_shim=FakeBoardShim,
        eeg_channels=[1, 2, 3, 4],
        timestamp_channel=13,
        poll_s=0.01,
    )
    acq.start()
    try:
        instance = FakeBoardShim.last_instance
        assert instance is not None
        assert instance.board_id == GANGLION_NATIVE_BOARD_ID
        assert not instance.params.serial_port
    finally:
        acq.stop()


def test_ble_start_failure_retries_instead_of_exiting(monkeypatch) -> None:
    calls = {"n": 0}

    def start(self) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("BOARD_NOT_CREATED_ERROR")

    monkeypatch.setattr(BrainFlowAcquisition, "start", start)
    monkeypatch.setattr(BrainFlowAcquisition, "next_chunk", lambda self: None)
    monkeypatch.setattr(BrainFlowAcquisition, "stop", lambda self: None)
    sink = ListSink()
    code = main(
        ["--hardware", "--ble", "--timeout", "1", "--duration-seconds", "0.05"],
        sink=sink,
    )
    assert code == 0
    assert calls["n"] >= 2
    details = [
        str(event["payload"].get("detail", ""))
        for event in sink.events
        if event["event_type"] == "device.status"
    ]
    assert any("retrying" in detail for detail in details)


def test_ble_cli_starts_without_serial_port(monkeypatch) -> None:
    monkeypatch.setattr(BrainFlowAcquisition, "start", lambda self: None)
    monkeypatch.setattr(BrainFlowAcquisition, "next_chunk", lambda self: None)
    monkeypatch.setattr(BrainFlowAcquisition, "stop", lambda self: None)
    sink = ListSink()
    code = main(["--hardware", "--ble", "--duration-seconds", "0.05"], sink=sink)
    assert code == 0
    statuses = [event for event in sink.events if event["event_type"] == "device.status"]
    assert statuses
    assert statuses[0]["payload"]["metadata"]["mode"] == "ble"


def test_connection_from_mapping_prefers_ble_over_empty_serial() -> None:
    conn = connection_from_mapping({"transport": "ble", "serial_port": None})
    assert conn.transport == "ble"
    assert conn.board_id == GANGLION_NATIVE_BOARD_ID
    conn.validate()


def test_simblee_is_a_ganglion_ble_name() -> None:
    from ganglion_adapter.ble_scan import is_ganglion_advertisement

    assert is_ganglion_advertisement("Simblee") is True
    assert is_ganglion_advertisement("Ganglion-XXXX") is True
    assert is_ganglion_advertisement("AirPods") is False


def test_list_devices_prints_simblee_from_ble_scan(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "ganglion_adapter.main.scan_ble_devices",
        lambda **_kwargs: [{"name": "Simblee", "address": "simblee-uuid", "rssi": -42}],
    )
    monkeypatch.setattr("ganglion_adapter.main.list_serial_candidates", lambda: [])
    code = main(["--hardware", "--list-devices"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Simblee" in out
    assert "simblee-uuid" in out
    assert "serial_number: Simblee" in out
