"use client";

import { useMemo, useState } from "react";

import { RobotSimulation, simulatedArmPose, type SimulationFrame } from "@/components/RobotSimulation";
import { StatusPill } from "@/components/Status";
import { api } from "@/lib/api";
import { percent, words } from "@/lib/format";
import { useBusyAction, useLive } from "@/lib/live";
import type { MachineState } from "@/lib/types";
import type { ArmPose } from "@/components/RobotSimulation";

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
  const pose = frame ? simulatedArmPose(frame, objects, target) : null;
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
          {machine?.machine_kind === "so_arm101" ? (
            <ArmPanel machine={machine} busy={busy} run={run} />
          ) : pose ? (
            <SimulatedJoints pose={pose} />
          ) : null}
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

const JOINT_ORDER = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"];

function ArmPanel({
  machine,
  busy,
  run,
}: {
  machine: MachineState;
  busy: boolean;
  run: (action: () => Promise<unknown>) => void;
}) {
  const ready = machine.state === "READY";
  const moving = machine.state === "EXECUTING" || machine.state === "HOLDING";
  const joints = machine.joints ?? {};
  const setpoint = machine.setpoint ?? {};
  const motion = machine.motion_live ? "Live: servos receive setpoints" : machine.backend === "lerobot" ? "Shadow: real arm read, never written" : "Virtual: dry run";
  return (
    <>
      <h3 className="sub">Arm</h3>
      <dl className="kv">
        <div><dt>Backend</dt><dd>{words(machine.backend)}</dd></div>
        <div><dt>Motion</dt><dd>{motion}</dd></div>
        <div><dt>Armed</dt><dd>{machine.armed ? "Armed" : machine.require_arming ? "Disarmed" : "Not required"}</dd></div>
        <div><dt>Skill</dt><dd>{machine.skill ? `${words(machine.skill)}${machine.waypoint ? ` · ${machine.waypoint}` : ""}` : "None"}</dd></div>
      </dl>
      <div className="btn-row">
        {machine.armed ? (
          <button type="button" className="btn" disabled={busy} onClick={() => run(() => api.machineControl("disarm"))}>
            Disarm
          </button>
        ) : (
          <button type="button" className="btn" disabled={busy || !ready} onClick={() => run(() => api.machineControl("arm"))}>
            Arm
          </button>
        )}
        <button
          type="button"
          className="btn"
          disabled={busy || !ready || moving || (machine.require_arming && !machine.armed)}
          onClick={() => run(() => api.machineControl("home"))}
        >
          Home
        </button>
      </div>
      {Object.keys(joints).length ? (
        <table className="joint-table">
          <thead>
            <tr><th>Joint</th><th>Measured</th><th>Setpoint</th></tr>
          </thead>
          <tbody>
            {JOINT_ORDER.filter((name) => name in joints).map((name) => (
              <tr key={name}>
                <td>{words(name)}</td>
                <td>{joints[name].toFixed(1)}</td>
                <td>{setpoint[name] !== undefined ? setpoint[name].toFixed(1) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </>
  );
}

const JOINT_UNITS: Record<string, string> = { gripper: "% open" };

function SimulatedJoints({ pose }: { pose: ArmPose }) {
  return (
    <>
      <h3 className="sub">Arm · SO-101 style, 6-DoF (simulated)</h3>
      <table className="joint-table">
        <thead>
          <tr><th>Joint</th><th>Angle</th></tr>
        </thead>
        <tbody>
          {JOINT_ORDER.map((name) => (
            <tr key={name}>
              <td>{words(name)}</td>
              <td>{Math.round(pose.joints[name] ?? 0)}{JOINT_UNITS[name] ? ` ${JOINT_UNITS[name]}` : "°"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted">{pose.reachable ? "Target within reach." : "Target at the edge of reach; the arm is stretched."} Angles come from the simulator's inverse kinematics, not from hardware.</p>
    </>
  );
}
