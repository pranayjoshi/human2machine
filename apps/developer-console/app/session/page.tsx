"use client";

import { EmergencyStop } from "@/components/EmergencyStop";
import { IntentInspector } from "@/components/IntentInspector";
import { Sparkline } from "@/components/Sparkline";
import { StatusPill } from "@/components/Status";
import { api } from "@/lib/api";
import { useBusyAction, useLive } from "@/lib/live";
import type { VisionState } from "@/lib/types";

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

export default function SessionPage() {
  const { snapshot, plots, connected } = useLive();
  const { busy, message, run } = useBusyAction();
  const session = snapshot?.session ?? null;

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
          {message ? <p className="error">{message}</p> : null}
        </section>
        <div className="live-bottom">
          <section className="panel">
            <h3>EEG (shadow, downsampled)</h3>
            <Sparkline plot={plots.eeg} label="Crown EEG placeholder" />
          </section>
          <section className="panel">
            <h3>EMG (downsampled)</h3>
            <Sparkline plot={plots.emg} label="Ganglion EMG placeholder" />
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
