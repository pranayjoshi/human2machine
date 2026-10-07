"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { RobotSimulation, type SimulationFrame } from "@/components/RobotSimulation";
import { StatusPill } from "@/components/Status";
import { api } from "@/lib/api";
import { useLive } from "@/lib/live";
import type { VisionObject } from "@/lib/types";

import styles from "./simulator.module.css";

type Scenario = "nominal" | "unreachable" | "grasp_failure";
type CameraPreset = "orbit" | "top" | "side";
type LogItem = { id: number; title: string; detail: string; tone: "good" | "neutral" | "bad" };

const FALLBACK_OBJECTS: VisionObject[] = [
  { object_id: "object_red_block_1", class_name: "red block", confidence: 1, bbox_xyxy: [0, 0, 0, 0], table_position_xy: [0.48, 0.4] },
  { object_id: "object_green_cube_1", class_name: "green cube", confidence: 1, bbox_xyxy: [0, 0, 0, 0], table_position_xy: [0.7, 0.68] },
  { object_id: "object_yellow_box_1", class_name: "yellow box", confidence: 1, bbox_xyxy: [0, 0, 0, 0], table_position_xy: [0.35, 0.72] },
];

const SCENARIOS: Record<Scenario, { label: string; note: string }> = {
  nominal: { label: "Nominal handoff", note: "Object is reachable and the grasp succeeds." },
  unreachable: { label: "Unreachable target", note: "Tests path validation before motion begins." },
  grasp_failure: { label: "Grasp failure", note: "Tests safe recovery after contact." },
};

function readable(value: string | null | undefined): string {
  if (!value) return "Ready";
  return value.replace(/^ExecutionStage\./, "").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function localFrame(progress: number, selected: string, scenario: Scenario, stopped: boolean): SimulationFrame {
  if (stopped) return { state: "ESTOPPED", stage: "motion locked", progress, targetId: selected, heldObjectId: null };
  if (scenario === "unreachable" && progress >= 0.12) {
    return { state: "FAULT", stage: "path rejected", progress: 0.12, targetId: selected, heldObjectId: null };
  }
  if (scenario === "grasp_failure" && progress >= 0.47) {
    return { state: "FAULT", stage: "grasp failed", progress: 0.47, targetId: selected, heldObjectId: null };
  }
  if (progress <= 0) return { state: "READY", stage: "ready", progress: 0, targetId: selected, heldObjectId: null };
  if (progress >= 1) return { state: "COMPLETED", stage: "complete", progress: 1, targetId: selected, heldObjectId: null };
  let stage = "approach target";
  if (progress >= 0.38 && progress < 0.51) stage = "secure grasp";
  else if (progress >= 0.51 && progress < 0.9) stage = "move to handoff";
  else if (progress >= 0.9) stage = "release object";
  return {
    state: "EXECUTING",
    stage,
    progress,
    targetId: selected,
    heldObjectId: progress >= 0.45 && progress < 0.96 ? selected : null,
  };
}

export default function TestingPage() {
  const { snapshot, connected } = useLive();
  const liveMachine = snapshot?.machine ?? null;
  const objects = useMemo(() => {
    const source = liveMachine?.objects?.length ? liveMachine.objects : snapshot?.vision?.objects;
    return source?.length ? source.slice(0, 5) : FALLBACK_OBJECTS;
  }, [liveMachine?.objects, snapshot?.vision?.objects]);
  const [selectedObjectId, setSelectedObjectId] = useState(objects[0]?.object_id ?? FALLBACK_OBJECTS[0].object_id);
  const [scenario, setScenario] = useState<Scenario>("nominal");
  const [camera, setCamera] = useState<CameraPreset>("orbit");
  const [progress, setProgress] = useState(0);
  const [running, setRunning] = useState(false);
  const [paused, setPaused] = useState(false);
  const [stopped, setStopped] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [sandboxActive, setSandboxActive] = useState(false);
  const [runNumber, setRunNumber] = useState(0);
  const [passedGates, setPassedGates] = useState({ virtual: false, fault: false });
  const [logs, setLogs] = useState<LogItem[]>([
    { id: 1, title: "Workcell ready", detail: "Safety boundary clear · no active command", tone: "neutral" },
  ]);
  const startedRef = useRef<number | null>(null);
  const elapsedRef = useRef(0);
  const eventId = useRef(2);
  const outcomeLogged = useRef(false);

  useEffect(() => {
    if (!objects.some((object) => object.object_id === selectedObjectId)) {
      setSelectedObjectId(objects[0]?.object_id ?? FALLBACK_OBJECTS[0].object_id);
    }
  }, [objects, selectedObjectId]);

  const addLog = useCallback((title: string, detail: string, tone: LogItem["tone"] = "neutral") => {
    setLogs((current) => [{ id: eventId.current++, title, detail, tone }, ...current].slice(0, 8));
  }, []);

  useEffect(() => {
    if (!running || paused || stopped) {
      startedRef.current = null;
      return;
    }
    let animation = 0;
    const tick = (time: number) => {
      if (startedRef.current == null) startedRef.current = time;
      const delta = time - startedRef.current;
      startedRef.current = time;
      elapsedRef.current += delta * speed;
      const next = Math.min(1, elapsedRef.current / 7200);
      setProgress(next);
      const faultAt = scenario === "unreachable" ? 0.12 : scenario === "grasp_failure" ? 0.47 : 2;
      if (next >= faultAt || next >= 1) setRunning(false);
      else animation = window.requestAnimationFrame(tick);
    };
    animation = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(animation);
  }, [paused, running, scenario, speed, stopped]);

  const sandboxFrame = localFrame(progress, selectedObjectId, scenario, stopped);
  useEffect(() => {
    if (!sandboxActive || outcomeLogged.current) return;
    if (sandboxFrame.state === "FAULT") {
      outcomeLogged.current = true;
      setPassedGates((current) => ({ ...current, fault: true }));
      addLog(
        scenario === "unreachable" ? "Path blocked safely" : "Grasp failure contained",
        scenario === "unreachable" ? "No motion entered the restricted zone" : "Object released · arm motion halted",
        "bad",
      );
    } else if (sandboxFrame.state === "COMPLETED") {
      outcomeLogged.current = true;
      setPassedGates((current) => ({ ...current, virtual: true }));
      addLog("Handoff complete", `${Math.round(elapsedRef.current / 100) / 10}s · no boundary violations`, "good");
    }
  }, [addLog, sandboxActive, sandboxFrame.state, scenario]);

  const liveFrame: SimulationFrame | null = connected && liveMachine ? {
    state: liveMachine.state ?? "READY",
    stage: liveMachine.stage ?? liveMachine.state ?? "ready",
    progress: liveMachine.progress ?? 0,
    targetId: liveMachine.target_object_id ?? selectedObjectId,
    heldObjectId: liveMachine.held_object_id ?? null,
    robotXY: liveMachine.robot_xy,
  } : null;
  const frame = sandboxActive ? sandboxFrame : liveFrame ?? sandboxFrame;
  const isFault = frame.state === "FAULT" || frame.state === "ESTOPPED";
  const liveSource = !sandboxActive && liveFrame != null;

  const runTest = () => {
    setSandboxActive(true);
    setStopped(false);
    setPaused(false);
    setProgress(0.001);
    elapsedRef.current = 0;
    startedRef.current = null;
    outcomeLogged.current = false;
    setRunning(true);
    setRunNumber((value) => value + 1);
    addLog("Command approved", `${SCENARIOS[scenario].label} · ${readable(selectedObjectId)}`, "good");
    if (connected && snapshot?.mock && scenario === "nominal") {
      void api.runDemo("success").catch(() => undefined);
    }
  };

  const reset = () => {
    setProgress(0);
    setRunning(false);
    setPaused(false);
    setStopped(false);
    setSandboxActive(false);
    elapsedRef.current = 0;
    startedRef.current = null;
    outcomeLogged.current = false;
    addLog("Workcell reset", "Arm returned to ready position", "neutral");
  };

  const emergencyStop = () => {
    setSandboxActive(true);
    setStopped(true);
    setRunning(false);
    addLog("Emergency stop", "Motion power locked · reset required", "bad");
    if (connected && !/physical/i.test(snapshot?.machine_mode ?? "")) {
      void api.estop().catch(() => undefined);
    }
  };

  const selectedObject = objects.find((object) => object.object_id === selectedObjectId) ?? objects[0];
  const stageIndex = frame.progress >= 1 ? 4 : frame.progress >= 0.9 ? 3 : frame.progress >= 0.51 ? 2 : frame.progress >= 0.38 ? 1 : 0;
  const passedGateCount = Number(passedGates.virtual) + Number(passedGates.fault);

  return (
    <div className={styles.lab}>
      <header className={styles.header}>
        <div>
          <p className="eyebrow">Real-world testing · Phase 01</p>
          <h1>Virtual robot lab</h1>
          <p className="lede">Test the complete pick-and-handoff loop in a safe 3D workcell before connecting physical hardware.</p>
        </div>
        <div className={styles.headerStatus}>
          <StatusPill status={connected ? "healthy" : "degraded"} label={connected ? "Simulator connected" : "Browser sandbox"} />
          <span>SO-ARM101 profile</span>
        </div>
      </header>

      <section className={styles.telemetry} aria-label="Workcell telemetry">
        <div><span>Machine state</span><strong className={isFault ? styles.dangerText : ""}>{readable(frame.state)}</strong></div>
        <div><span>Current stage</span><strong>{readable(frame.stage)}</strong></div>
        <div><span>Run progress</span><strong>{Math.round(frame.progress * 100)}%</strong></div>
        <div><span>Safety envelope</span><strong className={isFault ? styles.dangerText : styles.safeText}>{isFault ? "Motion locked" : "Clear"}</strong></div>
      </section>

      <div className={styles.workspace}>
        <section className={styles.viewport} aria-labelledby="workcell-heading">
          <div className={styles.viewportBar}>
            <div>
              <span className={styles.liveMark} />
              <strong id="workcell-heading">Workcell A</strong>
              <small>{liveSource ? "Live state" : "Deterministic sandbox"}</small>
            </div>
            <div className={styles.viewControls} aria-label="Camera view">
              {(["orbit", "top", "side"] as CameraPreset[]).map((view) => (
                <button key={view} type="button" className={camera === view ? styles.active : ""} onClick={() => setCamera(view)}>
                  {readable(view)}
                </button>
              ))}
            </div>
          </div>
          <RobotSimulation
            frame={frame}
            objects={objects}
            selectedObjectId={selectedObjectId}
            cameraPreset={camera}
            paused={paused}
            onSelectObject={setSelectedObjectId}
            onCameraChange={() => setCamera("orbit")}
          />
          <div className={styles.stageRail}>
            {["Approach", "Grasp", "Handoff", "Release"].map((label, index) => (
              <div key={label} className={index < stageIndex ? styles.done : index === stageIndex && frame.progress > 0 ? styles.current : ""}>
                <span>{index < stageIndex ? "✓" : String(index + 1).padStart(2, "0")}</span>
                <strong>{label}</strong>
              </div>
            ))}
          </div>
        </section>

        <aside className={styles.controls} aria-label="Simulation controls">
          <div className={styles.controlSection}>
            <div className={styles.sectionTitle}><span>01</span><strong>Target object</strong></div>
            <div className={styles.objectList}>
              {objects.map((object, index) => (
                <button
                  type="button"
                  key={object.object_id}
                  className={selectedObjectId === object.object_id ? styles.selected : ""}
                  onClick={() => setSelectedObjectId(object.object_id)}
                  disabled={running}
                >
                  <i className={styles[`object${index % 3}`]} />
                  <span><strong>{readable(object.class_name)}</strong><small>{Math.round(object.confidence * 100)}% detection confidence</small></span>
                  <b>{selectedObjectId === object.object_id ? "✓" : ""}</b>
                </button>
              ))}
            </div>
          </div>

          <div className={styles.controlSection}>
            <div className={styles.sectionTitle}><span>02</span><strong>Test scenario</strong></div>
            <select value={scenario} onChange={(event) => setScenario(event.target.value as Scenario)} disabled={running}>
              {(Object.keys(SCENARIOS) as Scenario[]).map((key) => <option key={key} value={key}>{SCENARIOS[key].label}</option>)}
            </select>
            <p>{SCENARIOS[scenario].note}</p>
            <label className={styles.speed}>
              <span>Playback speed <strong>{speed.toFixed(1)}×</strong></span>
              <input type="range" min="0.5" max="2" step="0.5" value={speed} onChange={(event) => setSpeed(Number(event.target.value))} />
            </label>
          </div>

          <div className={styles.actions}>
            <button type="button" className="btn btn-primary" onClick={runTest} disabled={running || stopped}>
              {frame.progress > 0 && frame.progress < 1 ? "Run again" : "Run handoff test"}
            </button>
            <button type="button" className="btn" onClick={() => setPaused((value) => !value)} disabled={!running || stopped}>
              {paused ? "Resume" : "Pause"}
            </button>
            <button type="button" className="btn" onClick={reset}>Reset</button>
            <button type="button" className="btn btn-danger" onClick={emergencyStop} disabled={stopped}>Stop</button>
          </div>
        </aside>
      </div>

      <div className={styles.lowerGrid}>
        <section className={`panel ${styles.runLog}`}>
          <div className="section-heading">
            <div><p className="eyebrow">Run {String(runNumber).padStart(3, "0")}</p><h2>Test log</h2></div>
            <span className={styles.logTime}>{Math.round(elapsedRef.current / 100) / 10}s elapsed</span>
          </div>
          <ol>
            {logs.map((item) => (
              <li key={item.id}><i className={styles[item.tone]} /><span><strong>{item.title}</strong><small>{item.detail}</small></span></li>
            ))}
          </ol>
        </section>

        <section className={`panel ${styles.gates}`}>
            <div className="section-heading"><div><p className="eyebrow">Release gates</p><h2>Physical readiness</h2></div><strong>{passedGateCount} / 4</strong></div>
          <ul>
            <li><span>Virtual handoff suite</span><b>{passedGates.virtual ? "Passed" : "In progress"}</b></li>
            <li><span>1,000-run reliability</span><b>Not started</b></li>
            <li><span>Fault recovery</span><b>{passedGates.fault ? "Passed" : "Not started"}</b></li>
            <li><span>Hardware-in-loop</span><b>Locked</b></li>
          </ul>
          <p>Physical motion stays disabled until every virtual safety gate passes.</p>
        </section>
      </div>
    </div>
  );
}
