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
        for check in required:
            if check["status"] == "healthy":
                continue
            assert check["id"] == "audio-adapter"
            assert check["status"] == "degraded"


def test_preflight_allows_live_mic_without_asr(mock_app) -> None:
    runtime = mock_app.state.runtime
    runtime._services["audio-adapter"]["reported_status"] = "degraded"
    runtime._services["audio-adapter"]["detail"] = "asr_unavailable"
    result = runtime.preflight()
    audio = next(check for check in result.checks if check["id"] == "audio-adapter")
    assert audio["status"] == "degraded"
    assert result.ready is True


def test_preflight_allows_capture_started_despite_degraded_heartbeat(mock_app) -> None:
    runtime = mock_app.state.runtime
    runtime._services["audio-adapter"]["reported_status"] = "degraded"
    runtime._services["audio-adapter"]["detail"] = "microphone capture started"
    result = runtime.preflight()
    assert result.ready is True
    runtime._services["audio-adapter"]["detail"] = "microphone capture started (mlx-whisper)"
    assert runtime.preflight().ready is True
    runtime._services["audio-adapter"]["detail"] = (
        "microphone is silent; grant Microphone permission to Terminal or Cursor"
    )
    assert runtime.preflight().ready is True


def test_preflight_blocks_disconnected_microphone(mock_app) -> None:
    runtime = mock_app.state.runtime
    runtime._services["audio-adapter"]["reported_status"] = "degraded"
    runtime._services["audio-adapter"]["detail"] = "microphone disconnected"
    result = runtime.preflight()
    assert result.ready is False
