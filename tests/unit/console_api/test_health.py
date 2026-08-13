from fastapi.testclient import TestClient


def test_health_ok(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "console-api"
    assert body["mock"] is True


def test_public_config_omits_secrets(client: TestClient) -> None:
    response = client.get("/api/config/public")
    assert response.status_code == 200
    body = response.json()
    dumped = str(body).lower()
    assert "password" not in dumped
    assert "token" not in dumped
    assert body["machine_mode"] == "simulator_only"
    assert "console_api" in body["ports"]
