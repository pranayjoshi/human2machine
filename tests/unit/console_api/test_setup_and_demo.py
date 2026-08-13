from __future__ import annotations

from typing import Any

from console_api.app import create_app
from fastapi.testclient import TestClient
from intent_contracts.validation import parse_unnormalized_event


class FakePush:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def send_event(self, event: Any) -> None:
        if hasattr(event, "to_unnormalized_dict"):
            payload = event.to_unnormalized_dict()
        else:
            payload = dict(event)
        payload.pop("normalized_time_ns", None)
        parse_unnormalized_event(payload)
        self.sent.append(payload)

    def close(self) -> None:
        return None


def test_setup_shape(client: TestClient) -> None:
    response = client.get("/api/setup")
    assert response.status_code == 200
    body = response.json()
    dumped = str(body).lower()
    assert "password" not in dumped
    assert "token" not in dumped
    assert isinstance(body["mock"], bool)
    assert body["machine_mode"]
    assert body["eeg_shadow_only"] is True
    assert "adapter_push" in body["ports"]
    assert "console_api" in body["ports"]
    assert isinstance(body["crown"]["env_vars_present"], bool)
    assert body["crown"]["shadow_only"] is True
    assert isinstance(body["ganglion"]["serial_port_set"], bool)
    assert "camera_index" in body["vision"]
    assert isinstance(body["audio"]["device_name_set"], bool)
    assert body["simulator"]["mode"]
    assert isinstance(body["checklist"], list)
    assert {item["id"] for item in body["checklist"]} >= {
        "crown",
        "ganglion",
        "audio",
        "vision",
        "simulator",
    }
    assert body["links"]
    assert any("03_DEVICE_CONNECTION.md" in link["path"] for link in body["links"])


def test_setup_doc_is_public_markdown(client: TestClient) -> None:
    response = client.get("/api/docs/device-connection")
    assert response.status_code == 200
    text = response.text
    assert "Neurosity Crown" in text
    assert "OpenBCI Ganglion" in text
    assert "/calibrate/emg" in text


def test_demo_run_accepts_scenarios(monkeypatch) -> None:
    monkeypatch.setattr("console_api.runtime.time.sleep", lambda _seconds: None)
    push = FakePush()
    app = create_app(mock=True, event_push=push)
    with TestClient(app) as client:
        for scenario in ("success", "conflict", "cancel"):
            push.sent.clear()
            response = client.post("/api/demo/run", json={"scenario": scenario})
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["ok"] is True
            assert body["scenario"] == scenario
            assert body["events_injected"] >= 1
            assert len(push.sent) == body["events_injected"]
            for event in push.sent:
                assert "normalized_time_ns" not in event
                parse_unnormalized_event(event)


def test_demo_run_rejects_unknown_scenario(client: TestClient) -> None:
    response = client.post("/api/demo/run", json={"scenario": "explode"})
    assert response.status_code == 422


def test_emg_calibration_stub(client: TestClient) -> None:
    started = client.post("/api/calibrate/emg/start")
    assert started.status_code == 200
    body = started.json()
    assert body["phase"] == "rest"
    assert body["eeg_used"] is False
    assert body["training_job"] is None
    status = client.get("/api/calibrate/emg/status")
    assert status.json()["phase"] == "rest"
    nxt = client.post("/api/calibrate/emg/next")
    assert nxt.json()["phase"] == "confirm"
    recorded = client.post("/api/calibrate/emg/record")
    assert recorded.json()["counts"]["confirm"] == 1
