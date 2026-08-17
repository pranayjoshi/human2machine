from __future__ import annotations

import time

import numpy as np
from crown_adapter.brainflow_client import (
    CROWN_BOARD_ID,
    BrainFlowCrownClient,
    CrownOscConnection,
    FallbackCrownClient,
    connection_from_mapping,
)
from crown_adapter.client import CrownAuthError, CrownClient, CrownEpoch


class FakeCrownBoardShim:
    last_instance: FakeCrownBoardShim | None = None

    def __init__(self, board_id: int, params) -> None:
        self.board_id = board_id
        self.params = params
        self.prepared = False
        self.streaming = False
        self.released = False
        self.stopped = False
        self.stream_buffer = None
        FakeCrownBoardShim.last_instance = self

    def prepare_session(self) -> None:
        self.prepared = True

    def is_prepared(self) -> bool:
        return self.prepared

    def start_stream(self, *args, **_kwargs) -> None:
        if not self.prepared:
            raise RuntimeError("prepare_session was not called")
        self.streaming = True
        self.stream_buffer = args[0] if args else None

    def get_board_data(self) -> np.ndarray:
        if not self.streaming:
            return np.zeros((20, 0))
        n = 16
        data = np.zeros((20, n), dtype=float)
        for idx, channel in enumerate(range(1, 9)):
            data[channel] = 10.0 + idx
        data[19] = 1_700_000_000.0 + np.arange(n) / 256.0
        return data

    def stop_stream(self) -> None:
        self.streaming = False
        self.stopped = True

    def release_session(self) -> None:
        self.released = True
        self.prepared = False

    @staticmethod
    def get_eeg_channels(_board_id: int) -> list[int]:
        return list(range(1, 9))

    @staticmethod
    def get_timestamp_channel(_board_id: int) -> int:
        return 19


def test_connection_from_mapping_keeps_nickname() -> None:
    connection = connection_from_mapping(
        {},
        ip_address="10.0.0.17",
        device_id="Crown-995",
        env={},
    )
    assert connection.device_id == "Crown-995"
    assert connection.ip_port == 9000


def test_connection_from_yaml_and_env() -> None:
    connection = connection_from_mapping(
        {"ip_address": "10.0.0.9", "device_id": "Crown-old", "ip_port": 9000},
        env={"CROWN_IP": "ignored-when-yaml-set", "NEUROSITY_DEVICE_ID": "ignored"},
    )
    assert connection.device_id == "Crown-old"
    assert connection.ip_port == 9000
    from_env = connection_from_mapping(
        {},
        env={"CROWN_IP": "10.0.0.17", "NEUROSITY_DEVICE_ID": "Crown-995"},
    )
    assert from_env.device_id == "Crown-995"


def test_missing_ip_is_ok_for_osc_broadcast() -> None:
    connection = CrownOscConnection(ip_address="", device_id="Crown-995")
    connection.validate()


def test_osc_client_listens_on_9000_then_emits_epochs() -> None:
    connection = CrownOscConnection(ip_address="", device_id="Crown-995", ip_port=9000)
    client = BrainFlowCrownClient(
        connection,
        board_shim=FakeCrownBoardShim,
        board_id=CROWN_BOARD_ID,
        eeg_channels=list(range(1, 9)),
        timestamp_channel=19,
        poll_s=0.01,
    )
    epochs: list[CrownEpoch] = []
    client.login()
    instance = FakeCrownBoardShim.last_instance
    assert instance is not None
    assert instance.board_id == CROWN_BOARD_ID
    assert instance.params.ip_port == 9000
    assert instance.params.ip_address == ""
    assert instance.stream_buffer == 45000
    client.start(epochs.append, lambda _accel: None)
    try:
        deadline = time.time() + 2.0
        while time.time() < deadline and not epochs:
            time.sleep(0.02)
        assert epochs
        first = epochs[0]
        assert first.channel_names == ["CP3", "C3", "F5", "PO3", "PO4", "F6", "C4", "CP4"]
        assert first.sampling_rate == 256.0
        assert len(first.data) == 8
        assert len(first.data[0]) == 16
        assert first.data[0][0] == 10.0
    finally:
        client.stop()
    assert instance.stopped is True
    assert instance.released is True
    assert instance.streaming is False


class _FailOsc(CrownClient):
    def login(self) -> None:
        raise CrownAuthError("no OSC packets on UDP 9000 in 5s")

    def start(self, on_epoch, on_accel) -> None:
        return None

    def stop(self) -> None:
        return None


class _SdkOk(CrownClient):
    login_calls = 0

    def login(self) -> None:
        _SdkOk.login_calls += 1

    def start(self, on_epoch, on_accel) -> None:
        return None

    def stop(self) -> None:
        return None


def test_start_stream_failure_does_not_raise_on_release() -> None:
    class BoomBoard(FakeCrownBoardShim):
        def start_stream(self, *_args, **_kwargs) -> None:
            raise RuntimeError("no data received in 5sec")

    connection = CrownOscConnection(ip_port=9000)
    client = BrainFlowCrownClient(connection, board_shim=BoomBoard)
    try:
        client.login()
    except CrownAuthError as exc:
        assert "UDP 9000" in str(exc)
    else:
        raise AssertionError("expected CrownAuthError")
    client.stop()
    instance = BoomBoard.last_instance
    assert instance is not None
    assert instance.is_prepared() is False


def test_fallback_uses_sdk_when_osc_is_silent() -> None:
    _SdkOk.login_calls = 0
    client = FallbackCrownClient(
        CrownOscConnection(),
        osc_client=_FailOsc(),
        sdk_client=_SdkOk(),
    )
    client.login()
    assert client.backend == "sdk"
    assert _SdkOk.login_calls == 1
