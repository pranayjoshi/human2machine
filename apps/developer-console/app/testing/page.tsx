"use client";

import { useMemo, useState } from "react";

import { RobotSimulation, type SimulationFrame } from "@/components/RobotSimulation";
import { StatusPill } from "@/components/Status";
import { api } from "@/lib/api";
import { percent, words } from "@/lib/format";
import { useBusyAction, useLive } from "@/lib/live";

type CameraPreset = "orbit" | "top" | "side";
const STAGES = ["Approach", "Grasp", "Handoff", "Release"];

function stageIndex(progress: number): number {
  if (progress >= 1) return 4;
  if (progress >= 0.9) return 3;
  if (progress >= 0.51) return 2;
  if (progress >= 0.38) return 1;
  return 0;
}

export default function RobotPage() {
  const { snapshot, connected } = useLive();
  const { busy, message, run } = useBusyAction();
  const [camera, setCamera] = useState<CameraPreset>("orbit");
  const machine = snapshot?.machine ?? null;
  const objects = useMemo(
    () => (machine?.objects?.length ? machine.objects : snapshot?.vision?.objects ?? []),
    [machine?.objects, snapshot?.vision?.objects],
  );
  const mode = snapshot?.machine_mode ?? "simulator_only";
  const faulted = machine?.state === "FAULT" || machine?.state === "ESTOPPED" || snapshot?.estop_latched;
  const progress = machine?.progress ?? 0;
  const current = stageIndex(progress);
  const target = machine?.target_object_id ?? machine?.active_command?.target_object_id ?? "";

  const frame: SimulationFrame | null = machine
    ? {
        state: machine.state ?? "READY",
        stage: machine.stage ?? machine.state ?? "ready",
        progress,
        targetId: target,
        heldObjectId: machine.held_object_id ?? null,
        robotXY: machine.robot_xy,
      }
    : null;
  const outcome = machine?.last_outcome as { outcome?: string; action?: string; target_object_id?: string } | null | undefined;

  return (
    <div className="robot">
      <header className="page-title">
        <div>
          <h1>Robot</h1>
          <p className="muted">
            Live state from the {/physical/i.test(mode) ? "physical robot" : "robot simulator"}. Commands only arrive here after the
            safety gateway approves them.
          </p>
        </div>
        <div className="btn-row">
          <StatusPill status={!connected || !machine ? "offline" : faulted ? "offline" : "healthy"} label={!machine ? "No machine state" : words(machine.state)} />
          {faulted ? (
            <button type="button" className="btn" disabled={busy} onClick={() => run(() => api.reset())}>
              Reset after checking workspace
            </button>
          ) : null}
        </div>
      </header>
      {message ? <p className="error">{message}</p> : null}

      <div className="robot-grid">
        <section className="card robot-view">
          <header className="card-head">
            <h2>Workcell</h2>
            <div className="seg" role="group" aria-label="Camera view">
              {(["orbit", "top", "side"] as CameraPreset[]).map((view) => (
                <button key={view} type="button" aria-pressed={camera === view} onClick={() => setCamera(view)}>
                  {words(view)}
                </button>
              ))}
            </div>
          </header>
          {frame ? (
            <RobotSimulation
              frame={frame}
              objects={objects}
              selectedObjectId={target}
              cameraPreset={camera}
              paused={false}
              onSelectObject={() => undefined}
              onCameraChange={() => setCamera("orbit")}
            />
          ) : (
            <div className="robot-empty">
              <strong>No machine state</strong>
              <span>Start the stack; the robot simulator publishes its state every few hundred milliseconds.</span>
            </div>
          )}
          <ol className="stage-rail">
            {STAGES.map((label, index) => (
              <li key={label} className={index < current ? "done" : index === current && progress > 0 ? "current" : ""}>
                {label}
              </li>
            ))}
          </ol>
        </section>

        <aside className="card">
          <header className="card-head"><h2>Status</h2></header>
          <dl className="kv">
            <div><dt>State</dt><dd>{words(machine?.state)}</dd></div>
            <div><dt>Stage</dt><dd>{words(machine?.stage)}</dd></div>
            <div><dt>Progress</dt><dd>{percent(progress)}</dd></div>
            <div><dt>Command</dt><dd>{machine?.active_command ? `${words(machine.active_command.action)} · ${words(machine.active_command.target_object_id)}` : "None"}</dd></div>
            <div><dt>Holding</dt><dd>{words(machine?.held_object_id, "Nothing")}</dd></div>
            <div><dt>Fault</dt><dd>{machine?.fault_reason ?? "None"}</dd></div>
            <div><dt>Last outcome</dt><dd>{outcome?.outcome ? `${words(outcome.outcome)}${outcome.target_object_id ? ` · ${words(outcome.target_object_id)}` : ""}` : "—"}</dd></div>
            <div><dt>Mode</dt><dd>{words(mode)}</dd></div>
          </dl>
          <h3 className="sub">Objects in workcell</h3>
          {objects.length ? (
            <ul className="object-list">
              {objects.map((object) => (
                <li key={object.object_id} className={object.object_id === target ? "target" : ""}>
                  <strong>{words(object.class_name)}</strong>
                  <span className="muted">{percent(object.confidence)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">No objects reported by the camera.</p>
          )}
        </aside>
      </div>
    </div>
  );
}
