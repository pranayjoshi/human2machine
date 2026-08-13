from fastapi.testclient import TestClient


def test_preflight_shape(client: TestClient) -> None:
    response = client.post("/api/preflight")
    assert response.status_code == 200
    body = response.json()
    assert "ready" in body
    assert isinstance(body["ready"], bool)
    assert isinstance(body["checks"], list)
    assert body["checks"], "expected preflight checks"
    ids = {check["id"] for check in body["checks"]}
    assert "crown-adapter" in ids
    assert "ganglion-adapter" in ids
    assert "audio-adapter" in ids
    assert "vision-adapter" in ids
    assert "event-hub" in ids
    assert "fusion-runtime" in ids
    assert "safety-gateway" in ids
    assert "robot-simulator" in ids
    assert "session-recorder" in ids
    assert "recorder-storage" in ids
    for check in body["checks"]:
        assert "name" in check
        assert "status" in check
        assert "message" in check
        assert "required" in check
        assert "last_event_age_ms" in check
    crown = next(check for check in body["checks"] if check["id"] == "crown-adapter")
    assert crown["required"] is False
    required = [check for check in body["checks"] if check["required"]]
    assert required
    if body["ready"]:
        assert all(check["status"] == "healthy" for check in required)
