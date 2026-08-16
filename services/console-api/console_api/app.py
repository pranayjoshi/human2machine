"""FastAPI application: browser gateway. The UI never talks to ZeroMQ."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from intent_contracts.control import SessionStartRequest, TrialStartRequest
from pydantic import BaseModel, ConfigDict, Field

from console_api.control_plane import ControlTransport
from console_api.demo import SCENARIOS
from console_api.runtime import CLIENT_QUEUE_MAX, ConsoleRuntime


class TrialLabelRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    ground_truth_action: str | None = None
    ground_truth_target: str | None = None
    notes: str | None = None
    user_correction: str | None = None


class ReplayRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    source: str = "fixtures"
    session_id: str | None = None
    speed: float = Field(default=1.0, gt=0)


class DemoRunRequest(BaseModel):
    scenario: Literal["success", "conflict", "cancel"]


def create_app(
    *,
    mock: bool = False,
    control_transport: ControlTransport | None = None,
    event_push: Any | None = None,
) -> FastAPI:
    runtime = ConsoleRuntime(
        mock=mock,
        control_transport=control_transport,
        event_push=event_push,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime.attach_loop(asyncio.get_running_loop())
        runtime.start()
        app.state.runtime = runtime
        try:
            yield
        finally:
            runtime.stop()

    app = FastAPI(title="Intent Compiler Console API", lifespan=lifespan)
    app.state.runtime = runtime
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def _control_or_error(response: Any) -> dict[str, Any]:
        payload = response.model_dump(mode="json")
        if not response.ok:
            raise HTTPException(status_code=400, detail=payload)
        return payload

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "service": "console-api", "mock": runtime.mock}

    @app.get("/api/services")
    def services() -> dict[str, Any]:
        return {"services": runtime.service_views()}

    @app.get("/api/config/public")
    def public_config() -> dict[str, Any]:
        return runtime.public_config()

    @app.get("/api/snapshot")
    def snapshot() -> dict[str, Any]:
        return runtime.snapshot()

    @app.post("/api/preflight")
    def preflight() -> dict[str, Any]:
        return runtime.preflight().model_dump(mode="json")

    @app.post("/api/sessions")
    def start_session(body: SessionStartRequest) -> dict[str, Any]:
        return _control_or_error(runtime.start_session(body.model_dump()))

    @app.get("/api/sessions")
    def list_sessions() -> dict[str, Any]:
        return {"sessions": runtime.list_sessions()}

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str) -> dict[str, Any]:
        session = runtime.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        return session

    @app.post("/api/sessions/{session_id}/stop")
    def stop_session(session_id: str) -> dict[str, Any]:
        return _control_or_error(runtime.stop_session(session_id))

    @app.post("/api/sessions/{session_id}/trials")
    def start_trial(session_id: str, body: TrialStartRequest) -> dict[str, Any]:
        return _control_or_error(runtime.start_trial(session_id, body.model_dump()))

    @app.post("/api/trials/{trial_id}/label")
    def label_trial(trial_id: str, body: TrialLabelRequest) -> dict[str, Any]:
        return runtime.label_trial(trial_id, body.model_dump())

    @app.post("/api/confirmations/{confirmation_id}/confirm")
    def confirm(confirmation_id: str) -> dict[str, Any]:
        return runtime.confirm(confirmation_id)

    @app.post("/api/confirmations/{confirmation_id}/cancel")
    def cancel_confirmation(confirmation_id: str) -> dict[str, Any]:
        return runtime.cancel_confirmation(confirmation_id)

    @app.post("/api/machine/estop")
    def estop() -> dict[str, Any]:
        return runtime.estop()

    @app.post("/api/machine/reset")
    def reset_machine() -> dict[str, Any]:
        return runtime.reset_estop()

    @app.post("/api/replay")
    def replay(body: ReplayRequest) -> dict[str, Any]:
        result = runtime.replay(body.model_dump())
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result)
        return result

    @app.get("/api/setup")
    def setup() -> dict[str, Any]:
        return runtime.setup_status()

    @app.get("/api/docs/{slug}")
    def setup_doc(slug: str) -> FileResponse:
        path = runtime.doc_path(slug)
        if path is None:
            raise HTTPException(status_code=404, detail="document not found")
        return FileResponse(path, media_type="text/markdown; charset=utf-8")

    @app.post("/api/demo/run")
    def run_demo(body: DemoRunRequest) -> dict[str, Any]:
        if body.scenario not in SCENARIOS:
            raise HTTPException(status_code=400, detail="unknown demo scenario")
        return runtime.run_demo(body.scenario)

    @app.post("/api/calibrate/emg/start")
    def calibrate_emg_start() -> dict[str, Any]:
        return runtime.calibrate_emg_start()

    @app.get("/api/calibrate/emg/status")
    def calibrate_emg_status() -> dict[str, Any]:
        return runtime.calibrate_emg_status()

    @app.post("/api/calibrate/emg/next")
    def calibrate_emg_next() -> dict[str, Any]:
        return runtime.calibrate_emg_next()

    @app.post("/api/calibrate/emg/record")
    def calibrate_emg_record() -> dict[str, Any]:
        return runtime.calibrate_emg_record()

    @app.post("/api/calibrate/vision/complete")
    def calibrate_vision_complete() -> dict[str, Any]:
        return runtime.complete_vision_calibration()

    @app.post("/api/calibrate/eeg/acknowledge")
    def calibrate_eeg_acknowledge() -> dict[str, Any]:
        return runtime.acknowledge_eeg_calibration()

    @app.websocket("/api/live")
    async def live(websocket: WebSocket) -> None:
        await websocket.accept()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=CLIENT_QUEUE_MAX)
        runtime.add_client(queue)
        await websocket.send_json({"type": "snapshot", "payload": runtime.snapshot()})

        async def sender() -> None:
            while True:
                message = await queue.get()
                await websocket.send_json(message)

        async def receiver() -> None:
            while True:
                incoming = await websocket.receive_json()
                if incoming.get("type") in {"snapshot", "resync", "hello"}:
                    await websocket.send_json({"type": "snapshot", "payload": runtime.snapshot()})

        try:
            await asyncio.gather(sender(), receiver())
        except (WebSocketDisconnect, RuntimeError):
            # Browser disconnect must not change machine state.
            pass
        finally:
            runtime.remove_client(queue)

    return app
