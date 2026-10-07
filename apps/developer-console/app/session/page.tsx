"use client";

import { useEffect, useState } from "react";

import { Sparkline } from "@/components/Sparkline";
import { StatusPill } from "@/components/Status";
import { API_BASE, api } from "@/lib/api";
import { useBusyAction, useLive } from "@/lib/live";
import type {
  BiosignalHealth,
  DemoScenario,
  LiveState,
  ModalityFeature,
  PlotSnapshot,
  VisionState,
} from "@/lib/types";

function words(value: string | null | undefined): string {
  if (!value) return "Waiting";
  return value
    .replace(/^object_/, "")
    .replace(/_1$/, "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function percent(value: number | null | undefined): string {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}

function age(value: number | null | undefined): string {
  if (value == null) return "No data";
  if (value < 1000) return `${Math.round(value)} ms ago`;
  return `${(value / 1000).toFixed(1)} s ago`;
}

function signalStatus(health?: BiosignalHealth): "healthy" | "degraded" | "offline" {
  if (!health || health.last_data_age_ms == null || health.last_data_age_ms > 5000) {
    return "offline";
  }
  if (
    (health.quality ?? 0) < 0.4 ||
    health.packet_loss_count > 0 ||
    health.sequence_gaps > 0
  ) {
    return "degraded";
  }
  return "healthy";
}

function confidence(feature?: ModalityFeature | null): number {
  return Math.max(0, Math.min(1, feature?.confidence ?? 0));
}

function SensorCard({
  title,
  value,
  detail,
  status,
  score,
}: {
  title: string;
  value: string;
  detail: string;
  status: string;
  score?: number | null;
}) {
  return (
    <article className="sensor-card">
      <header>
        <h3>{title}</h3>
        <StatusPill status={status} label={status === "healthy" ? "Live" : status} />
      </header>
      <p className="sensor-value">{value}</p>
      <p className="sensor-detail">{detail}</p>
      <div className="confidence-track" aria-label={score == null ? "No confidence" : `${percent(score)} confidence`}>
        <span style={{ width: `${Math.round((score ?? 0) * 100)}%` }} />
      </div>
    </article>
  );
}

function CameraView({
  vision,
  preview,
}: {
  vision: VisionState | null;
  preview: { available: boolean; width: number; height: number } | null | undefined;
}) {
  const objects = vision?.objects ?? [];
  const pointed = new Set((vision?.pointing_candidates ?? []).map((item) => item.object_id));
  const width = preview?.width || 1280;
  const height = preview?.height || 720;
  const live = Boolean(preview?.available);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!live) return;
    const id = window.setInterval(() => setTick((value) => value + 1), 350);
    return () => window.clearInterval(id);
  }, [live]);

  return (
    <section className="panel" aria-labelledby="camera-heading">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Workspace</p>
          <h2 id="camera-heading">What the camera sees</h2>
        </div>
        <StatusPill status={live ? "healthy" : "degraded"} label={live ? "Live" : "Overlay only"} />
      </div>
      <div className="camera">
        <div className="camera-stage">
          {live ? (
            <img
              src={`${API_BASE}/api/vision/preview?t=${tick}`}
              alt="Live tabletop camera"
              width={width}
              height={height}
            />
          ) : null}
          <svg viewBox={`0 0 ${width} ${height}`} aria-label="Detected object overlay" role="img">
            {!live ? <rect width={width} height={height} fill="#17191f" /> : null}
            {objects.map((object) => {
              const [x1, y1, x2, y2] = object.bbox_xyxy;
              const selected = pointed.has(object.object_id);
              return (
                <g key={object.object_id}>
                  <rect
                    x={x1}
                    y={y1}
                    width={x2 - x1}
                    height={y2 - y1}
                    fill="none"
                    stroke={selected ? "#f2c56d" : "#ffffff"}
                    strokeWidth={selected ? 5 : 2}
                  />
                  <text x={x1 + 7} y={y1 + 23} fill="#ffffff" fontSize="17">
                    {words(object.class_name)}
                  </text>
                </g>
              );
            })}
          </svg>
        </div>
      </div>
      <p className="camera-caption">
        {objects.length
          ? `${objects.length} object${objects.length === 1 ? "" : "s"} visible`
          : "No objects visible"}
        {vision?.pointing_candidates?.[0]
          ? ` · pointing toward ${words(vision.pointing_candidates[0].object_id)}`
          : ""}
      </p>
    </section>
  );
}

function DecisionCard({ snapshot }: { snapshot: LiveState | null }) {
  const intent = snapshot?.intent;
  const safety = snapshot?.safety;
  const machine = snapshot?.machine;
  const verdict = safety?.verdict;
  let title = "Waiting for a clear request";
  let explanation = "Speak naturally, point to an object, or use your calibrated gesture.";

  if (intent) {
    const action = words(intent.action);
    const target = intent.target_object_id ? words(intent.target_object_id) : null;
    title = target ? `${action} · ${target}` : action;
    if (verdict === "APPROVE") explanation = "The evidence was clear and the safety checks passed.";
    else if (verdict === "ASK_CONFIRMATION") explanation = "The request is plausible, but needs your confirmation.";
    else if (verdict === "HOLD") explanation = "The system is waiting because the available evidence is not strong enough.";
    else if (verdict === "REJECT") explanation = "The request was blocked by the safety policy.";
    else explanation = "Evidence is still being combined before a safe decision is made.";
  }

  return (
    <section className="decision-hero" aria-live="polite">
      <p className="eyebrow">Current interpretation</p>
      <h2>{title}</h2>
      <p className="muted">{explanation}</p>
      <div className="decision-meta">
        <span>
          Confidence
          <strong>{percent(intent?.confidence)}</strong>
        </span>
        <span>
          Safety
          <strong>{words(verdict)}</strong>
        </span>
        <span>
          Machine
          <strong>{words(machine?.state)}</strong>
        </span>
      </div>
    </section>
  );
}

function SignalDetail({
  title,
  note,
  health,
  feature,
  plot,
}: {
  title: string;
  note: string;
  health?: BiosignalHealth;
  feature?: ModalityFeature | null;
  plot: PlotSnapshot;
}) {
  const status = signalStatus(health);
  return (
    <article>
      <header className="section-heading">
        <div>
          <h3>{title}</h3>
          <p className="muted">{note}</p>
        </div>
        <StatusPill status={status} />
      </header>
      <dl className="kv">
        <div>
          <dt>Interpretation</dt>
          <dd>{words(feature?.label)}</dd>
        </div>
        <div>
          <dt>Confidence</dt>
          <dd>{percent(feature?.confidence)}</dd>
        </div>
        <div>
          <dt>Signal quality</dt>
          <dd>{percent(health?.quality)}</dd>
        </div>
        <div>
          <dt>Last sample</dt>
          <dd>{age(health?.last_data_age_ms)}</dd>
        </div>
      </dl>
      <Sparkline plot={plot} label={`${title} channels`} />
      {health?.flags?.length ? <p className="muted">Check: {health.flags.map(words).join(", ")}</p> : null}
    </article>
  );
}

function formatTimeline(kind: string, label: string): { title: string; detail: string } {
  const readable = words(label);
  if (kind === "safety") return { title: `Safety · ${readable}`, detail: "Policy evaluated the request" };
  if (kind === "machine") return { title: `Machine · ${readable}`, detail: "Machine state changed" };
  if (kind === "outcome") return { title: `Outcome · ${readable}`, detail: "Action finished" };
  if (kind === "control") return { title: readable, detail: "Operator control" };
  return { title: readable, detail: words(kind) };
}

export default function SessionPage() {
  const { snapshot, plots, connected } = useLive();
  const { busy, message, run } = useBusyAction();
  const session = snapshot?.session ?? null;
  const emg = snapshot?.features?.emg;
  const eeg = snapshot?.features?.eeg;
  const pointed = snapshot?.vision?.pointing_candidates?.[0];
  const [demoNote, setDemoNote] = useState<string | null>(null);

  const runDemo = (scenario: DemoScenario) => {
    setDemoNote(null);
    void run(async () => {
      const result = await api.runDemo(scenario);
      setDemoNote(`${words(scenario)} test sent · ${result.events_injected} events`);
    });
  };

  return (
    <>
      <header className="page-header">
        <div>
          <p className="eyebrow">Live workspace</p>
          <h1>Human signals, made useful.</h1>
          <p className="lede">One view of what you said, indicated, and confirmed—and what the system decided to do.</p>
        </div>
        <div className="btn-row">
          {session ? (
            <>
              <button
                type="button"
                className="btn"
                disabled={busy}
                onClick={() => run(() => api.startTrial(session.session_id, { instruction: "Live interaction" }))}
              >
                New interaction
              </button>
              <button
                type="button"
                className="btn"
                disabled={busy}
                onClick={() => run(() => api.stopSession(session.session_id))}
              >
                End session
              </button>
            </>
          ) : null}
        </div>
      </header>

      {!connected ? <p className="error" role="status">The live view is offline. Displayed values may be stale.</p> : null}
      {message ? <p className="error">{message}</p> : null}

      <section className="sensor-grid" aria-label="Live signal interpretations">
        <SensorCard
          title="Voice"
          value={snapshot?.audio?.transcript?.trim() || "Listening"}
          detail={
            snapshot?.audio?.action
              ? `${words(snapshot.audio.action)} · ${snapshot.audio.is_final ? "complete" : "listening"}`
              : "No request recognized yet"
          }
          status={snapshot?.audio ? "healthy" : "offline"}
          score={snapshot?.audio?.confidence}
        />
        <SensorCard
          title="Vision"
          value={pointed ? words(pointed.object_id) : `${snapshot?.vision?.objects?.length ?? 0} visible`}
          detail={pointed ? "Most likely pointing target" : "Waiting for a clear pointing target"}
          status={snapshot?.vision ? "healthy" : "offline"}
          score={pointed?.confidence}
        />
        <SensorCard
          title="EMG"
          value={words(emg?.label)}
          detail={emg?.shadow_only ? "Detected, currently monitoring only" : "Available to confirm or cancel"}
          status={signalStatus(snapshot?.biosignals?.emg)}
          score={confidence(emg)}
        />
        <SensorCard
          title="EEG"
          value={eeg?.label === "artifact" ? "Movement detected" : eeg ? "Signal clear" : "Waiting"}
          detail="Signal quality monitor · never commands the machine"
          status={signalStatus(snapshot?.biosignals?.eeg)}
          score={confidence(eeg)}
        />
      </section>

      <div className="live-grid" style={{ marginTop: "14px" }}>
        <CameraView vision={snapshot?.vision ?? null} preview={snapshot?.vision_preview} />
        <div className="live-stack">
          <DecisionCard snapshot={snapshot} />
          <section className="panel">
            <p className="eyebrow">Recent activity</p>
            <h2>Decision log</h2>
            <ol className="timeline">
              {(snapshot?.timeline ?? []).length ? (
                (snapshot?.timeline ?? []).slice(0, 8).map((item, index) => {
                  const row = formatTimeline(item.kind, item.label);
                  return (
                    <li key={`${item.t_ms}-${index}`}>
                      <time>{new Date(item.t_ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</time>
                      <span>
                        <strong>{row.title}</strong>
                        {row.detail}
                      </span>
                    </li>
                  );
                })
              ) : (
                <li>
                  <time>—</time>
                  <span><strong>No decisions yet</strong>Activity will appear here.</span>
                </li>
              )}
            </ol>
          </section>
        </div>

        <div className="live-bottom">
          <section className="panel">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Signal detail</p>
                <h2>Biosignal quality</h2>
              </div>
              <span className="muted">Raw traces stay available for diagnosis</span>
            </div>
            <div className="biosignal-grid">
              <SignalDetail
                title="Ganglion · EMG"
                note="Forearm gesture"
                health={snapshot?.biosignals?.emg}
                feature={emg}
                plot={plots.emg}
              />
              <SignalDetail
                title="Crown · EEG"
                note="Quality and artifact monitor"
                health={snapshot?.biosignals?.eeg}
                feature={eeg}
                plot={plots.eeg}
              />
            </div>
          </section>

          <section className="panel">
            <div className="section-heading">
              <div>
                <p className="eyebrow">System</p>
                <h2>Connections</h2>
              </div>
              <StatusPill status={connected ? "healthy" : "offline"} />
            </div>
            <div className="service-grid">
              {(snapshot?.services ?? []).map((service) => (
                <div className="service-row" key={service.id}>
                  <span><StatusPill status={service.status} label={service.name} /></span>
                  <small>{age(service.last_heartbeat_age_ms)}</small>
                </div>
              ))}
            </div>
          </section>
        </div>
      </div>

      {snapshot?.mock ? (
        <details className="test-tools">
          <summary>Simulation tools</summary>
          <div className="btn-row">
            <button type="button" className="btn" disabled={busy} onClick={() => runDemo("success")}>Clear request</button>
            <button type="button" className="btn" disabled={busy} onClick={() => runDemo("conflict")}>Conflicting signals</button>
            <button type="button" className="btn" disabled={busy} onClick={() => runDemo("cancel")}>Cancellation</button>
          </div>
          {demoNote ? <p className="muted" role="status">{demoNote}</p> : null}
        </details>
      ) : null}
    </>
  );
}
