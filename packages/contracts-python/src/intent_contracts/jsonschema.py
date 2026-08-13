from __future__ import annotations

import json
from pathlib import Path

from intent_contracts.commands import ActionCommand
from intent_contracts.control import ControlRequest, ControlResponse
from intent_contracts.envelope import EventEnvelope
from intent_contracts.events import (
    ActionOutcomePayload,
    AudioIntentPayload,
    BiosignalChunkPayload,
    IntentDecisionPayload,
    MachineStatePayload,
    ModalityFeaturePayload,
    SafetyDecisionPayload,
    ServiceHeartbeatPayload,
    VisionObjectsPayload,
)

MODELS = {
    "event_envelope": EventEnvelope,
    "action_command": ActionCommand,
    "control_request": ControlRequest,
    "control_response": ControlResponse,
    "biosignal_chunk_payload": BiosignalChunkPayload,
    "modality_feature_payload": ModalityFeaturePayload,
    "vision_objects_payload": VisionObjectsPayload,
    "audio_intent_payload": AudioIntentPayload,
    "intent_decision_payload": IntentDecisionPayload,
    "safety_decision_payload": SafetyDecisionPayload,
    "machine_state_payload": MachineStatePayload,
    "action_outcome_payload": ActionOutcomePayload,
    "service_heartbeat_payload": ServiceHeartbeatPayload,
}


def write_json_schema(output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, model in MODELS.items():
        path = output_dir / f"{name}.json"
        path.write_text(json.dumps(model.model_json_schema(), indent=2) + "\n")
        written.append(path)
    return written


if __name__ == "__main__":
    write_json_schema(Path("packages/contracts-python/schema"))
