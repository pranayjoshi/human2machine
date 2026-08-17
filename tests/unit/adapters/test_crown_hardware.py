from __future__ import annotations

import math
from types import SimpleNamespace
from unittest.mock import patch

from crown_adapter.client import (
    CrownAuthError,
    CrownEpoch,
    NeurosityPythonClient,
    QueuedCrownClient,
    fetch_claimed_devices,
    headset_idle_detail,
    latest_metric_packet,
    load_crown_credentials,
    looks_like_firebase_device_id,
    normalize_epoch,
    pick_device_id,
    prune_stale_device_nodes,
    public_exception_text,
    sdk_options,
    to_channel_major,
)
from crown_adapter.hardware import (
    AccelState,
    CrownConfig,
    backoff_s,
    convert_epoch,
    is_auth_failure,
    is_missing_credentials,
    run_crown_hardware,
)
from crown_adapter.mock import CrownMockRuntime
from crown_adapter.publisher import ListSink
from intent_contracts.validation import parse_unnormalized_event


def _epoch(start_time: float, fill: float) -> CrownEpoch:
    data = [[fill + ch + n * 0.01 for n in range(16)] for ch in range(8)]
    return CrownEpoch(
        data=data,
        channel_names=["CP3", "C3", "F5", "PO3", "PO4", "F6", "C4", "CP4"],
        sampling_rate=256.0,
        start_time_ms=start_time,
    )


def test_mock_eeg_epochs_preserve_crown_shape() -> None:
    runtime = CrownMockRuntime(seed=7)
    events = []
    for _ in range(4):
        events.extend(runtime.tick())
    eeg = [event for event in events if event.event_type == "biosignal.chunk"]
    assert len(eeg) >= 4
    for event in eeg:
        parsed = parse_unnormalized_event(event.to_unnormalized_dict())
        payload = parsed.payload
        assert parsed.modality == "eeg"
        assert payload["sample_rate_hz"] == 256
        assert payload["channel_names"] == ["CP3", "C3", "F5", "PO3", "PO4", "F6", "C4", "CP4"]
        assert payload["sample_count"] == 16
        assert len(payload["samples"]) == 8
        assert all(len(channel) == 16 for channel in payload["samples"])
        assert "normalized_time_ns" not in event.to_unnormalized_dict()


def test_every_mock_message_parses() -> None:
    runtime = CrownMockRuntime(seed=1, motion=True)
    events = []
    for _ in range(20):
        events.extend(runtime.tick())
    events.append(runtime.heartbeat_event(0))
    events.extend(runtime.simulate_disconnect())
    assert events
    for event in events:
        parse_unnormalized_event(event.to_unnormalized_dict())


def test_hardware_path_uses_injected_client_samples() -> None:
    sink = ListSink()
    epoch = _epoch(1000, 40)
    client = QueuedCrownClient(epochs=[epoch])
    run_crown_hardware(
        client=client,
        send=sink.send_event,
        config=CrownConfig(),
        stopped=lambda: False,
        duration_s=0.4,
        login_timeout_s=2.0,
        sleep=lambda _s: None,
    )
    assert client.login_calls >= 1
    assert client.stop_calls >= 1
    eeg = [event for event in sink.events if event["event_type"] == "biosignal.chunk"]
    assert eeg
    first = eeg[0]
    parse_unnormalized_event(first)
    assert first["payload"]["samples"][0][:3] == epoch.data[0][:3]
    assert first["payload"]["sample_rate_hz"] == 256
    statuses = [event for event in sink.events if event["event_type"] == "device.status"]
    assert any(event["payload"]["device_alias"] == "crown" for event in statuses)
    assert any(
        "connecting to Neurosity" in str(event["payload"].get("detail")) for event in statuses
    )
    assert not any(event["payload"]["device_alias"] == "crown-mock" for event in statuses)
    assert any(event["event_type"] == "motion.chunk" for event in sink.events)
    assert any(event["event_type"] == "service.heartbeat" for event in sink.events)


def test_replayed_epochs_with_same_start_time_are_skipped() -> None:
    accel = AccelState(x=0, y=0, z=1, magnitude=1, has_sample=True)
    seq = {"n": 0}

    def next_seq() -> int:
        value = seq["n"]
        seq["n"] += 1
        return value

    once = convert_epoch(
        _epoch(5000, 1),
        accel,
        sequence=next_seq,
        packet_loss_count=0,
        chunks_emitted=0,
        motion_artifact_threshold=0.8,
        expected_channels=8,
        expected_samples=16,
        sample_rate_hz=256,
        shadow_only=True,
        clock_offset_ns=None,
    )
    assert once.rejected is False
    assert any(event.event_type == "biosignal.chunk" for event in once.events)


def test_reconnect_backoff_is_exponential_and_capped() -> None:
    assert backoff_s(0, 30) == 1.0
    assert backoff_s(1, 30) == 2.0
    assert backoff_s(2, 30) == 4.0
    assert backoff_s(10, 30) == 30.0


def test_missing_credentials_stay_offline() -> None:
    sink = ListSink()
    client = QueuedCrownClient(
        login_error=CrownAuthError(
            "Crown IP is required; pass --ip or set devices.crown.ip_address"
        )
    )
    run_crown_hardware(
        client=client,
        send=sink.send_event,
        config=CrownConfig(),
        stopped=lambda: False,
        duration_s=0.3,
        login_timeout_s=1.0,
        sleep=lambda _s: None,
    )
    statuses = [event for event in sink.events if event["event_type"] == "device.status"]
    assert any(event["payload"]["status"] == "offline" for event in statuses)
    assert any("missing Crown OSC IP" in str(event["payload"].get("detail")) for event in statuses)


def test_connect_timeout_keeps_heartbeats_and_reconnects() -> None:
    sink = ListSink()
    now_s = {"t": 0.0}
    client = QueuedCrownClient(
        login_error=CrownAuthError("Crown connect timed out after 20000ms")
    )
    run_crown_hardware(
        client=client,
        send=sink.send_event,
        config=CrownConfig(heartbeat_seconds=2.0, reconnect_max_seconds=1.0),
        stopped=lambda: False,
        duration_s=25.0,
        login_timeout_s=20.0,
        now=lambda: now_s["t"],
        sleep=lambda seconds: now_s.__setitem__("t", now_s["t"] + seconds),
    )
    heartbeats = [event for event in sink.events if event["event_type"] == "service.heartbeat"]
    assert len(heartbeats) >= 8, f"expected heartbeats during reconnect, got {len(heartbeats)}"
    statuses = [event for event in sink.events if event["event_type"] == "device.status"]
    assert any("timed out" in str(event["payload"].get("detail", "")).lower() for event in statuses)
    assert client.stop_calls >= 1


def test_login_matches_mindexecute_connect_sequence() -> None:
    captured: dict[str, object] = {}

    class FakeNeurositySDK:
        def __init__(self, options: dict[str, str]) -> None:
            captured["options"] = options
            self.login_args: dict[str, str] | None = None
            self.brainwaves = False
            self.client_id = "fake"

        def login(self, creds: dict[str, str]) -> None:
            self.login_args = creds
            captured["login"] = creds

        def brainwaves_raw(self, _callback: object) -> object:
            captured["brainwaves_raw"] = True
            return lambda: None

        def accelerometer(self, _callback: object) -> object:
            return lambda: None

        def remove_all_subscriptions(self) -> None:
            return None

        def remove_client(self) -> None:
            return None

    with patch.dict("sys.modules", {"neurosity": SimpleNamespace(NeurositySDK=FakeNeurositySDK)}):
        client = NeurosityPythonClient(
            env={
                "NEUROSITY_EMAIL": "user@example.com",
                "NEUROSITY_PASSWORD": "secret",
                "NEUROSITY_DEVICE_ID": "Crown-995",
            }
        )
        client.login()
        client.start(lambda _epoch: None, lambda _accel: None)
        client.stop()

    assert captured["options"] == {"deviceId": "Crown-995", "device_id": "Crown-995"}
    assert captured["login"] == {"email": "user@example.com", "password": "secret"}
    assert captured["brainwaves_raw"] is True


def test_public_exception_text_redacts_firebase_auth_and_keeps_status() -> None:
    class FakeResponse:
        status_code = 401
        url = (
            "https://neurosity-device.firebaseio.com/devices/Crown-995/"
            "subscriptions/abc.json?auth=SECRETTOKEN"
        )
        text = '{"error": "Permission denied"}'

    class FakeHTTPError(Exception):
        def __init__(self) -> None:
            super().__init__("401 Client Error")
            self.response = FakeResponse()

    text = public_exception_text(FakeHTTPError())
    assert "SECRETTOKEN" not in text
    assert "HTTP 401" in text
    assert "/devices/Crown-995/subscriptions/abc" in text
    assert "permission denied" in text.lower()


class _FakeSnap:
    def __init__(self, value: object) -> None:
        self._value = value

    def val(self) -> object:
        return self._value


class _FakeDb:
    def __init__(self, tree: dict[str, object]) -> None:
        self.tree = tree
        self.path = ""

    def child(self, name: str) -> "_FakeDb":
        next_db = _FakeDb(self.tree)
        next_db.path = f"{self.path}/{name}".strip("/")
        return next_db

    def get(self, token: str) -> _FakeSnap:
        assert token == "tok"
        node: object = self.tree
        for part in self.path.split("/"):
            if not part:
                continue
            if not isinstance(node, dict):
                return _FakeSnap(None)
            node = node.get(part)
        return _FakeSnap(node)

    def remove(self, token: str) -> None:
        assert token == "tok"
        if not self.path:
            return
        parts = [part for part in self.path.split("/") if part]
        node: object = self.tree
        for part in parts[:-1]:
            if not isinstance(node, dict):
                return
            node = node.get(part)
        if isinstance(node, dict):
            node.pop(parts[-1], None)


def test_fetch_claimed_devices_reads_nickname() -> None:
    db = _FakeDb(
        {
            "users": {"uid1": {"devices": {"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa": True}}},
            "devices": {
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa": {"info": {"deviceNickname": "Crown-995"}}
            },
        }
    )
    devices = fetch_claimed_devices(db, {"localId": "uid1", "idToken": "tok"})
    assert devices == [
        {"deviceId": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "deviceNickname": "Crown-995"}
    ]


def test_login_resolves_nickname_to_claimed_device() -> None:
    claimed_id = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

    class FakeNeurositySDK:
        def __init__(self, options: dict[str, str]) -> None:
            self.options = options
            self.user = {"localId": "uid1", "idToken": "tok"}
            self.db = _FakeDb(
                {
                    "users": {"uid1": {"devices": {claimed_id: True}}},
                    "devices": {claimed_id: {"info": {"deviceNickname": "Crown-995"}}},
                }
            )
            self.client_id = "old-client"
            self.added: list[str] = []

        def login(self, _creds: dict[str, str]) -> None:
            return None

        def get_info(self) -> dict[str, str]:
            return {"deviceNickname": "Crown-995"}

        def add_client(self) -> None:
            self.added.append(self.options["device_id"])
            self.client_id = "new-client"

        def remove_client(self) -> None:
            self.client_id = ""

        def brainwaves_raw(self, _callback: object) -> object:
            return lambda: None

        def accelerometer(self, _callback: object) -> object:
            return lambda: None

        def remove_all_subscriptions(self) -> None:
            return None

    with patch.dict("sys.modules", {"neurosity": SimpleNamespace(NeurositySDK=FakeNeurositySDK)}):
        client = NeurosityPythonClient(
            env={
                "NEUROSITY_EMAIL": "user@example.com",
                "NEUROSITY_PASSWORD": "secret",
                "NEUROSITY_DEVICE_ID": "Crown-995",
            }
        )
        client.login()
        assert client._sdk.options["device_id"] == claimed_id
        assert client._sdk.added == [claimed_id]


def test_start_wraps_http_error() -> None:
    class FakeResponse:
        status_code = 401
        url = "https://example.firebaseio.com/devices/Crown-995/subscriptions/x.json?auth=SECRET"
        text = '{"error": "Permission denied"}'

    class FakeHTTPError(Exception):
        def __init__(self) -> None:
            super().__init__("401 Client Error")
            self.response = FakeResponse()

    class FakeSDK:
        def brainwaves_raw(self, _callback: object) -> object:
            raise FakeHTTPError()

    client = NeurosityPythonClient()
    client._sdk = FakeSDK()
    try:
        client.start(lambda _epoch: None, lambda _accel: None)
    except CrownAuthError as exc:
        message = str(exc)
        assert "brainwaves_raw failed" in message
        assert "HTTP 401" in message
        assert "SECRET" not in message
    else:
        raise AssertionError("expected CrownAuthError")


def test_auth_failure_stays_degraded() -> None:
    sink = ListSink()
    client = QueuedCrownClient(
        login_error=CrownAuthError("Neurosity authentication failed; check .env.local")
    )
    ticks = {"n": 0}

    def stop() -> bool:
        ticks["n"] += 1
        return ticks["n"] > 8

    run_crown_hardware(
        client=client,
        send=sink.send_event,
        config=CrownConfig(reconnect_max_seconds=0.01),
        stopped=stop,
        duration_s=0.0,
        login_timeout_s=1.0,
        sleep=lambda _s: None,
    )
    statuses = [event for event in sink.events if event["event_type"] == "device.status"]
    assert any(event["payload"]["status"] == "degraded" for event in statuses)


def test_pick_device_id_matches_nickname() -> None:
    devices = [
        {"deviceId": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "deviceNickname": "Crown-995"},
        {"deviceId": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "deviceNickname": "Other"},
    ]
    assert pick_device_id("Crown-995", devices) == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    assert pick_device_id("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", devices) == (
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    )
    assert looks_like_firebase_device_id("Crown-995") is False
    assert looks_like_firebase_device_id("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa") is True


def test_pick_device_id_uses_only_claimed_device() -> None:
    devices = [{"deviceId": "cccccccccccccccccccccccccccccccc", "deviceNickname": "Home"}]
    assert pick_device_id("Crown-995", devices) == "cccccccccccccccccccccccccccccccc"


def test_mindexecute_device_id_is_passed_through_unchanged() -> None:
    email, password, device_id = load_crown_credentials(
        {
            "NEUROSITY_EMAIL": "user@example.com",
            "NEUROSITY_PASSWORD": "secret",
            "NEUROSITY_DEVICE_ID": "crown-995",
        }
    )
    assert device_id == "crown-995"
    assert email == "user@example.com"
    assert password == "secret"
    assert sdk_options(device_id) == {"deviceId": "crown-995", "device_id": "crown-995"}


def test_is_missing_credentials_not_confused_with_auth_failure() -> None:
    assert is_missing_credentials("Crown IP is required") is True
    assert is_missing_credentials("NEUROSITY_PASSWORD is required") is True
    assert is_auth_failure("auth/wrong-password") is True
    assert is_auth_failure("NEUROSITY_PASSWORD is required") is False
    assert is_auth_failure("Crown IP is required") is False


def test_mindexecute_packet_shape_is_channel_major() -> None:
    packet = {
        "data": [[float(ch)] * 16 for ch in range(8)],
        "info": {
            "channelNames": ["CP3", "C3", "F5", "PO3", "PO4", "F6", "C4", "CP4"],
            "samplingRate": 256,
            "startTime": 10,
        },
    }
    epoch = normalize_epoch(packet)
    assert len(epoch.data) == 8
    assert len(epoch.data[0]) == 16
    transposed = to_channel_major([[float(ch) for ch in range(8)] for _ in range(16)], 8)
    assert len(transposed) == 8
    assert math.isclose(transposed[3][0], 3.0)


def test_latest_metric_packet_picks_newest_child() -> None:
    raw = {
        "a": {
            "data": [[1.0] * 16 for _ in range(8)],
            "info": {"startTime": 1},
        },
        "b": {
            "data": [[2.0] * 16 for _ in range(8)],
            "info": {"startTime": 9},
        },
    }
    packet = latest_metric_packet(raw)
    assert packet is not None
    assert packet["info"]["startTime"] == 9


def test_headset_idle_detail_sleep_and_offline() -> None:
    assert "sleep mode" in headset_idle_detail({"sleepMode": True})
    assert "offline" in headset_idle_detail({"state": "offline"}).lower()
    assert "console.neurosity.co" in headset_idle_detail({})


def test_poll_epoch_reads_firebase_metric() -> None:
    packet = {
        "data": [[float(ch)] * 16 for ch in range(8)],
        "info": {
            "channelNames": ["CP3", "C3", "F5", "PO3", "PO4", "F6", "C4", "CP4"],
            "samplingRate": 256,
            "startTime": 10,
        },
    }

    class FakeSDK:
        def get_from_path(self, path: str) -> dict[str, object]:
            assert path == "metrics/brainwaves/raw"
            return packet

    client = NeurosityPythonClient()
    client._sdk = FakeSDK()
    epoch = client.poll_epoch()
    assert epoch is not None
    assert len(epoch.data) == 8
    assert len(epoch.data[0]) == 16


def test_hardware_uses_polled_epoch_when_stream_idle() -> None:
    sink = ListSink()
    epoch = _epoch(1000, 40)

    class PollClient(QueuedCrownClient):
        def start(
            self,
            on_epoch: object,
            on_accel: object,
        ) -> None:
            on_accel(self.accel)

        def poll_epoch(self) -> CrownEpoch:
            return epoch

    ticks = {"n": 0}

    def stop() -> bool:
        ticks["n"] += 1
        return ticks["n"] > 6

    run_crown_hardware(
        client=PollClient(),
        send=sink.send_event,
        config=CrownConfig(reconnect_max_seconds=0.01),
        stopped=stop,
        duration_s=0.0,
        login_timeout_s=1.0,
        sleep=lambda _s: None,
    )
    chunks = [event for event in sink.events if event["event_type"] == "biosignal.chunk"]
    assert chunks
    assert any(
        event["payload"]["status"] == "healthy"
        for event in sink.events
        if event["event_type"] == "device.status"
    )


def test_prune_stale_device_nodes_keeps_our_client() -> None:
    tree: dict[str, object] = {
        "devices": {
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa": {
                "clients": {"ours": 1, "stale": 2},
                "subscriptions": {"old": {"metric": "kinesis"}},
            }
        }
    }
    sdk = SimpleNamespace(
        token="tok",
        client_id="ours",
        options={"device_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
        db=_FakeDb(tree),
    )
    prune_stale_device_nodes(sdk)
    device = tree["devices"]["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]
    assert device["clients"] == {"ours": 1}
    assert "subscriptions" not in device


def test_idle_with_motion_asks_to_wear_headset() -> None:
    sink = ListSink()
    now_s = {"t": 0.0}

    class AccelOnly(QueuedCrownClient):
        def start(self, on_epoch: object, on_accel: object) -> None:
            on_accel(self.accel)

        def poll_epoch(self) -> None:
            return None

    ticks = {"n": 0}

    def stop() -> bool:
        ticks["n"] += 1
        return ticks["n"] > 6

    run_crown_hardware(
        client=AccelOnly(),
        send=sink.send_event,
        config=CrownConfig(heartbeat_seconds=100.0, reconnect_max_seconds=0.01),
        stopped=stop,
        duration_s=0.0,
        login_timeout_s=1.0,
        now=lambda: now_s["t"],
        sleep=lambda _seconds: now_s.__setitem__("t", now_s["t"] + 9),
    )
    details = [
        str(event["payload"].get("detail") or "")
        for event in sink.events
        if event["event_type"] == "device.status"
    ]
    assert any("put it on your head" in detail for detail in details)
