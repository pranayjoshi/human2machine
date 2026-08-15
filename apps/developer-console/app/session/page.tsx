"use client";

import { useState } from "react";

import { EmergencyStop } from "@/components/EmergencyStop";
import { IntentInspector } from "@/components/IntentInspector";
import { Sparkline } from "@/components/Sparkline";
import { StatusPill } from "@/components/Status";
import { api } from "@/lib/api";
import { useBusyAction, useLive } from "@/lib/live";
import type { BiosignalHealth, DemoScenario, PlotSnapshot, VisionState } from "@/lib/types";

function CameraView({ vision }: { vision: VisionState | null }) {
  const objects = vision?.objects ?? [];
  const pointing = new Set((vision?.pointing_candidates ?? []).map((item) => item.object_id));
  return (
    <section className="panel" aria-labelledby="camera-heading">
      <h2 id="camera-heading">Camera / workspace</h2>
      <div className="camera">
        <svg viewBox="0 0 1280 720" role="img" aria-label="Object overlay from vision.objects">
          <rect width="1280" height="720" fill="#0a0d11" />
          <text x="24" y="40" fill="#9aa8b8" fontSize="22">
            Camera preview unavailable — overlay from vision events
          </text>
          {objects.map((obj) => {
            const [x1, y1, x2, y2] = obj.bbox_xyxy;
            return (
              <g key={obj.object_id}>
                <rect
                  x={x1}
                  y={y1}
                  width={x2 - x1}
                  height={y2 - y1}
                  fill="none"
                  stroke={pointing.has(obj.object_id) ? "#f8e38a" : "#e2e8f0"}
                  strokeWidth={pointing.has(obj.object_id) ? 6 : 3}
                />
                <text x={x1 + 6} y={y1 + 22} fill="#f8fafc" fontSize="18">
                  {obj.object_id} ({obj.class_name})
                </text>
              </g>
            );
          })}
        </svg>
      </div>
      <p className="camera-caption">
        Pointing candidates:{" "}
        {(vision?.pointing_candidates ?? [])
          .map((item) => `${item.object_id} ${item.confidence.toFixed(2)}`)
          .join(", ") || "none"}
      </p>
    </section>
  );
}

function formatAge(ageMs: number | null | undefined): string {
  if (ageMs == null) return "—";
  if (ageMs < 1000) return `${Math.round(ageMs)} ms`;
  return `${(ageMs / 1000).toFixed(1)} s`;
}

function formatQuality(quality: number | null | undefined): string {
  if (quality == null) return "—";
  return quality.toFixed(2);
}

function biosignalTone(health: BiosignalHealth | undefined): { status: string; label: string } {
  if (!health) {
    return { status: "offline", label: "No biosignal health yet" };
  }
  const age = health.last_data_age_ms;
  if (age != null && age > 5000) {
    return { status: "offline", label: "No recent data" };
  }
  if (health.packet_loss_count > 0 || health.sequence_gaps > 0) {
    return { status: "degraded", label: "Packet loss or sequence gaps" };
  }
  if (health.quality == null) {
    return { status: "offline", label: "Waiting for samples" };
  }
  if (health.quality >= 0.8) {
    return { status: "healthy", label: "Quality good" };
  }
  if (health.quality >= 0.4) {
    return { status: "degraded", label: "Quality degraded" };
  }
  return { status: "degraded", label: "Quality poor" };
}

function BiosignalStream({
  title,
  shadowNote,
  health,
  plot,
  sparkLabel,
}: {
  title: string;
  shadowNote: string;
  health: BiosignalHealth | undefined;
  plot: PlotSnapshot;
  sparkLabel: string;
}) {
  const tone = biosignalTone(health);
  return (
    <article>
      <h3>{title}</h3>
      <p className="muted">{shadowNote}</p>
      <p>
        <StatusPill status={tone.status} label={tone.label} />
      </p>
      <dl className="kv">
        <div>
          <dt>Quality</dt>
          <dd>{formatQuality(health?.quality)}</dd>
        </div>
        <div>
          <dt>Packet loss count</dt>
          <dd>{health?.packet_loss_count ?? "—"}</dd>
        </div>
        <div>
          <dt>Sequence gaps</dt>
          <dd>{health?.sequence_gaps ?? "—"}</dd>
        </div>
        <div>
          <dt>Last data age</dt>
          <dd>{formatAge(health?.last_data_age_ms)}</dd>
        </div>
      </dl>
      <Sparkline plot={plot} label={sparkLabel} />
    </article>
  );
}

export default function SessionPage() {
  const { snapshot, plots, connected } = useLive();
  const { busy, message, run } = useBusyAction();
  const session = snapshot?.session ?? null;
  const [demoNote, setDemoNote] = useState<string | null>(null);

  const runDemo = (scenario: DemoScenario) => {
    setDemoNote(null);
    void run(async () => {
      const result = await api.runDemo(scenario);
      setDemoNote(
        `Injected ${result.events_injected} ${scenario} events` +
          (result.pushed ? " to the hub." : " into the mock console path."),
      );
    });
  };

  return (
    <>
      <h1>Live session</h1>
      {!connected ? (
        <p className="error" role="status">
          Live stream is disconnected. State is stale until the console API reconnects. A browser
          disconnect does not stop the machine.
        </p>
      ) : null}
      <div className="live-grid">
        <section className="panel" aria-labelledby="health-heading">
          <h2 id="health-heading">Service health</h2>
          <ul className="checklist">
            {(snapshot?.services ?? []).map((service) => (
              <li key={service.id}>
                <StatusPill status={service.status} /> {service.name}
                <div className="check-meta">
                  age {service.last_heartbeat_age_ms ?? "—"} ms · missed {service.missed_heartbeats}
                </div>
              </li>
            ))}
          </ul>
        </section>
        <CameraView vision={snapshot?.vision ?? null} />
        <section className="panel" aria-labelledby="intent-heading">
          <h2 id="intent-heading">Request and safety</h2>
          <p>
            Audio: {snapshot?.audio?.transcript || "—"}{" "}
            {snapshot?.audio?.is_final ? "(final)" : snapshot?.audio ? "(partial)" : ""}
          </p>
          <IntentInspector intent={snapshot?.intent ?? null} safety={snapshot?.safety ?? null} />
          {session ? (
            <div className="btn-row">
              <button
                type="button"
                className="btn"
                disabled={busy}
                onClick={() =>
                  run(() =>
                    api.startTrial(session.session_id, {
                      instruction: "Give me that object",
                      ground_truth_action: "REQUEST_HANDOFF",
                      ground_truth_target: "object_blue_1",
                    }),
                  )
                }
              >
                Start trial
              </button>
              <button
                type="button"
                className="btn"
                disabled={busy}
                onClick={() => run(() => api.stopSession(session.session_id))}
              >
                Stop session
              </button>
              <EmergencyStop latched={Boolean(snapshot?.estop_latched)} />
            </div>
          ) : (
            <p className="muted">No active session. Complete preflight to start one.</p>
          )}
          <h3>Run demo trial</h3>
          <p className="muted">
            Injects a timed audio + vision + EMG sequence. With the hub up, events PUSH to port
            5555. In mock-only mode they still appear in this console.
          </p>
          <div className="btn-row">
            <button
              type="button"
              className="btn btn-primary"
              disabled={busy}
              onClick={() => runDemo("success")}
            >
              Demo: success
            </button>
            <button type="button" className="btn" disabled={busy} onClick={() => runDemo("conflict")}>
              Demo: conflict
            </button>
            <button type="button" className="btn" disabled={busy} onClick={() => runDemo("cancel")}>
              Demo: cancel
            </button>
          </div>
          {demoNote ? <p role="status">{demoNote}</p> : null}
          {message ? <p className="error">{message}</p> : null}
        </section>
        <div className="live-bottom">
          <section className="panel biosignal-panel" aria-labelledby="biosignal-heading">
            <h2 id="biosignal-heading">Biosignal acquisition</h2>
            <p className="muted">
              EEG and EMG are recorded for quality and later experiments. They do not drive actions
              in Milestone 1.
            </p>
            <div className="biosignal-grid">
              <BiosignalStream
                title="Crown EEG"
                shadowNote="Shadow-only — does not drive action"
                health={snapshot?.biosignals?.eeg}
                plot={plots.eeg}
                sparkLabel="Crown EEG (downsampled, shadow-only)"
              />
              <BiosignalStream
                title="Ganglion EMG"
                shadowNote="Shadow-only for Milestone 1 — does not drive action"
                health={snapshot?.biosignals?.emg}
                plot={plots.emg}
                sparkLabel="Ganglion EMG (downsampled, shadow-only)"
              />
            </div>
          </section>
          <section className="panel">
            <h3>Audio status</h3>
            <p>{snapshot?.audio?.action ?? "no action"}</p>
            <p className="muted">
              confidence {snapshot?.audio?.confidence?.toFixed(2) ?? "—"} ·{" "}
              {snapshot?.audio?.is_final ? "final" : "waiting"}
            </p>
          </section>
          <section className="panel">
            <h3>Machine timeline</h3>
            <ol className="timeline">
              {(snapshot?.timeline ?? []).map((item, index) => (
                <li key={`${item.t_ms}-${index}`}>
                  {item.kind}: {item.label}
                </li>
              ))}
            </ol>
            <p className="muted">Machine: {snapshot?.machine?.state ?? "unknown"}</p>
          </section>
        </div>
      </div>
    </>
  );
}
