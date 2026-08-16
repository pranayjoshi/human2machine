from __future__ import annotations

from fastapi.testclient import TestClient


def test_snapshot_includes_biosignal_shadow_only(client: TestClient) -> None:
    response = client.get("/api/snapshot")
    assert response.status_code == 200
    body = response.json()
    eeg = body["biosignals"]["eeg"]
    emg = body["biosignals"]["emg"]
    assert eeg["shadow_only"] is True
    assert emg["shadow_only"] is True
    assert "quality" in eeg
    assert "packet_loss_count" in eeg
    assert "sequence_gaps" in eeg
    assert "last_data_age_ms" in eeg
    assert "last_sequence" in eeg
    assert "sample_rate_hz" in eeg


def test_public_config_mentions_shadow_flags(client: TestClient) -> None:
    response = client.get("/api/config/public")
    assert response.status_code == 200
    fusion = response.json()["fusion"]
    assert fusion["eeg_shadow_only"] is True
    assert fusion["emg_shadow_only"] is True


def test_snapshot_tracks_biosignal_chunk_and_sequence_gap(mock_app) -> None:
    runtime = mock_app.state.runtime
    runtime.ingest_event(
        {
            "event_id": "eegchunk00000001",
            "event_type": "biosignal.chunk",
            "source": "crown-adapter",
            "modality": "eeg",
            "sequence": 1,
            "quality": 0.91,
            "payload": {
                "sample_rate_hz": 256.0,
                "channel_names": ["C3"],
                "sample_count": 1,
                "samples": [[0.1]],
                "packet_loss_count": 2,
            },
        }
    )
    runtime.ingest_event(
        {
            "event_id": "hubquality000001",
            "event_type": "data.quality",
            "source": "event-hub",
            "sequence": 9,
            "quality": 0.25,
            "payload": {
                "score": 0.25,
                "components": {"sequence_integrity": 0.0},
                "flags": ["sequence_gap"],
                "producer": "crown-adapter",
                "previous_sequence": 1,
                "sequence": 5,
                "kind": "gap",
            },
        }
    )
    snapshot = runtime.snapshot()
    eeg = snapshot["biosignals"]["eeg"]
    assert eeg["shadow_only"] is True
    assert eeg["packet_loss_count"] == 2
    assert eeg["sequence_gaps"] == 1
    assert eeg["last_sequence"] == 5
    assert eeg["quality"] == 0.25
    assert eeg["sample_rate_hz"] == 256.0
