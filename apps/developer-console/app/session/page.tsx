"use client";

import { useEffect, useState } from "react";

import { EmergencyStop } from "@/components/EmergencyStop";
import { IntentInspector } from "@/components/IntentInspector";
import { Sparkline } from "@/components/Sparkline";
import { StatusPill } from "@/components/Status";
import { api, API_BASE } from "@/lib/api";
import { useBusyAction, useLive } from "@/lib/live";
import type { BiosignalHealth, DemoScenario, LiveState, PlotSnapshot, VisionState } from "@/lib/types";

function CameraView({
  vision,
  preview,
}: {
  vision: VisionState | null;
  preview: { available: boolean; width: number; height: number } | null | undefined;
}) {
  const objects = vision?.objects ?? [];
  const pointing = new Set((vision?.pointing_candidates ?? []).map((item) => item.object_id));
  const width = preview?.width || 1280;
  const height = preview?.height || 720;
  const live = Boolean(preview?.available);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!live) {
      return;
    }
    const id = window.setInterval(() => setTick((value) => value + 1), 250);
    return () => window.clearInterval(id);
  }, [live]);
  return (
    <section className="panel" aria-labelledby="camera-heading">
      <h2 id="camera-heading">Camera / workspace</h2>
      <div className="camera">
        <div className="camera-stage">
          {live ? (
            <img
              src={`${API_BASE}/api/vision/preview?t=${tick}`}
              alt="Live camera preview"
              width={width}
              height={height}
            />
          ) : null}
          <svg
            viewBox={`0 0 ${width} ${height}`}
            role="img"
            aria-label="Object overlay from vision.objects"
          >
            {live ? null : (
              <>
                <rect width={width} height={height} fill="#0a0d11" />
                <text x="24" y="40" fill="#9aa8b8" fontSize={Math.max(18, width / 40)}>
                  Camera preview unavailable — overlay from vision events
                </text>
              </>
            )}
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
      </div>
      <p className="camera-caption">
        Pointing candidates:{" "}
        {(vision?.pointing_candidates ?? []).map((item) => `${item.object_id} ${item.confidence.toFixed(2)}`).join(", ") ||
          "none"}
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

function audioCaptureStatus(snapshot: LiveState | null): string {
  const service = snapshot?.services?.find((item) => item.id === "audio-adapter");
  if (!service) {
    return "Audio adapter has not reported yet.";
  }
  const detail = service.detail?.trim();
  if (detail) {
    return detail;
  }
  if (service.status === "offline") {
    return "Audio adapter is offline.";
  }
  return "Microphone is up. Speak a command, then pause.";
}

function AudioStatusPanel({ snapshot }: { snapshot: LiveState | null }) {
  const audio = snapshot?.audio;
  const transcript = audio?.transcript?.trim() ?? "";
  const service = snapshot?.services?.find((item) => item.id === "audio-adapter");
  const listening = Boolean(
    service?.listening || service?.detail?.toLowerCase().includes("speech detected"),
  );
  const silent = Boolean(service?.detail?.toLowerCase().includes("silent"));
  const emptyAsr = Boolean(service?.detail?.toLowerCase().includes("no words"));
  let transcriptLabel = "No transcript yet. Speak a command, then pause for about half a second.";
  if (transcript) {
    transcriptLabel = transcript;
  } else if (silent) {
    transcriptLabel = "Microphone is silent. Grant Microphone permission to Terminal or Cursor.";
  } else if (listening) {
    transcriptLabel = "Listening… waiting for a pause to transcribe.";
  } else if (emptyAsr) {
    transcriptLabel = "Heard speech, but ASR returned no words.";
  }
  const phase = audio?.is_final ? "final" : audio ? "partial" : listening ? "listening" : silent ? "silent" : "waiting";
  const rms = service?.rms;
  const backend = service?.asr_backend;
  return (
    <section className="panel" aria-labelledby="audio-heading">
      <h3 id="audio-heading">Audio status</h3>
      <p className="audio-transcript" aria-live="polite">
        {transcriptLabel}
      </p>
      <p>{audio?.action ?? "no action"}</p>
      <p className="muted">
        confidence {audio?.confidence?.toFixed(2) ?? "—"} · {phase}
        {backend ? ` · ${backend}` : ""}
        {rms != null ? ` · mic ${rms.toFixed(4)}` : ""}
      </p>
      <p className="muted">{audioCaptureStatus(snapshot)}</p>
    </section>
  );
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
  detail,
}: {
  title: string;
  shadowNote: string;
  health: BiosignalHealth | undefined;
  plot: PlotSnapshot;
  sparkLabel: string;
  detail?: string | null;
}) {
  const tone = biosignalTone(health);
  return (
    <article>
      <h3>{title}</h3>
      <p className="muted">{shadowNote}</p>
      <p>
        <StatusPill status={tone.status} label={tone.label} />
      </p>
      {detail ? <p className="muted">{detail}</p> : null}
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
                  {service.detail ? ` · ${service.detail}` : ""}
                </div>
              </li>
            ))}
          </ul>
        </section>
        <CameraView vision={snapshot?.vision ?? null} preview={snapshot?.vision_preview} />
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
                detail={snapshot?.services?.find((item) => item.id === "crown-adapter")?.detail}
              />
              <BiosignalStream
                title="Ganglion EMG"
                shadowNote="Shadow-only for Milestone 1 — does not drive action"
                health={snapshot?.biosignals?.emg}
                plot={plots.emg}
                sparkLabel="Ganglion EMG (downsampled, shadow-only)"
                detail={snapshot?.services?.find((item) => item.id === "ganglion-adapter")?.detail}
              />
            </div>
          </section>
          <AudioStatusPanel snapshot={snapshot} />
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
