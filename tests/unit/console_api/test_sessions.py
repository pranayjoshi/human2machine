from console_api.app import create_app
from fastapi.testclient import TestClient
from intent_contracts.control import ControlRequest, ControlResponse
from intent_contracts.enums import ControlMethod, SessionState


def test_session_start_maps_to_control_request() -> None:
    seen: list[ControlRequest] = []

    def fake_rep(request: ControlRequest) -> ControlResponse:
        seen.append(request)
        return ControlResponse(
            ok=True,
            request_id=request.request_id,
            method=request.method,
            session_id="session_test_1",
            state=SessionState.RECORDING,
            payload={"user_id": request.payload.get("user_id")},
        )

    app = create_app(mock=True, control_transport=fake_rep)
    with TestClient(app) as client:
        response = client.post(
            "/api/sessions",
            json={
                "user_id": "alice",
                "record_audio": False,
                "record_video": False,
                "consent": True,
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["session_id"] == "session_test_1"
    assert body["state"] == "RECORDING"
    assert len(seen) == 1
    request = seen[0]
    assert request.method == ControlMethod.SESSION_START
    assert request.request_id
    assert request.payload["user_id"] == "alice"
    assert request.payload["consent"] is True


def test_session_start_mock_fallback(client: TestClient) -> None:
    response = client.post("/api/sessions", json={"user_id": "primary", "consent": True})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["session_id"]
    listed = client.get("/api/sessions")
    assert listed.status_code == 200
    ids = {item["session_id"] for item in listed.json()["sessions"]}
    assert body["session_id"] in ids
    detail = client.get(f"/api/sessions/{body['session_id']}")
    assert detail.status_code == 200
    assert detail.json()["user_id"] == "primary"


def test_session_start_requires_consent(client: TestClient) -> None:
    response = client.post("/api/sessions", json={"consent": False})
    assert response.status_code == 400
