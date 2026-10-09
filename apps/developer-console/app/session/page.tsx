"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { Sparkline } from "@/components/Sparkline";
import { StatusPill } from "@/components/Status";
import { API_BASE, api } from "@/lib/api";
import { VERDICT_COPY, ago, clock, objectName, percent, signalTone, words, type Tone } from "@/lib/format";
import { useBusyAction, useLive } from "@/lib/live";
import type {
  BiosignalHealth,
  DemoScenario,
  LiveState,
  ModalityFeature,
  PlotSnapshot,
  PreflightResult,
  ServiceView,
  VisionState,
} from "@/lib/types";

function service(snapshot: LiveState | null, key: string): ServiceView | undefined {
  return snapshot?.services.find((item) => item.id.includes(key));
}

function serviceTone(item?: ServiceView): Tone {
  return (item?.status as Tone | undefined) ?? "offline";
}

/* ───────────────────────── Session bar ───────────────────────── */

function SessionBar({ snapshot }: { snapshot: LiveState | null }) {
  const { busy, message, run } = useBusyAction();
  const [preflight, setPreflight] = useState<PreflightResult | null>(null);
  const [consent, setConsent] = useState(false);
  const [instruction, setInstruction] = useState("");
  const session = snapshot?.session ?? null;

  const check = useCallback(() => run(async () => setPreflight(await api.preflight())), [run]);
  useEffect(() => {
    if (!session) void check();
  }, [session, check]);

  if (!session) {
    const required = preflight?.checks.filter((item) => item.required) ?? [];
    const blocking = required.filter((item) => item.status !== "healthy");
    return (
      <section className="session-bar" aria-label="Session">
        <div className="session-bar-main">
          <div>
            <h1>No session running</h1>
            <p className="muted">
              {preflight == null
                ? "Checking devices…"
                : blocking.length
                  ? `${required.length - blocking.length} of ${required.length} required services ready.`
                  : "All required services are ready."}
            </p>
          </div>
          <div className="session-actions">
            <label className="consent">
              <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
              Participant consented to recording
            </label>
            <button type="button" className="btn" disabled={busy} onClick={() => void check()}>
              Re-check
            </button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={busy || !consent}
              title={consent ? undefined : "Confirm consent first"}
              onClick={() =>
                run(async () => {
                  const result = await api.startSession({ consent: true });
                  if (!result.ok) throw new Error(result.error ?? "Session did not start");
                })
              }
            >
              Start session
            </button>
          </div>
        </div>
        {blocking.length ? (
          <ul className="blockers">
            {blocking.map((item) => (
              <li key={item.id}>
                <StatusPill status={item.status} label={item.name} />
                <span>{item.recovery ?? item.message}</span>
              </li>
            ))}
            <li>
              <Link className="text-link" href="/setup">Open setup →</Link>
            </li>
          </ul>
        ) : null}
        {message ? <p className="error">{message}</p> : null}
      </section>
    );
  }

  const trials = session.trials ?? [];
  const activeTrial = snapshot?.active_trial_id ?? null;
  return (
    <section className="session-bar" aria-label="Session">
      <div className="session-bar-main">
        <div>
          <h1>
            Session <span className="mono">{session.session_id.replace(/^session_/, "").slice(0, 8)}</span>
          </h1>
          <p className="muted">
            {trials.length} trial{trials.length === 1 ? "" : "s"}
            {activeTrial ? " · trial in progress" : " · speak, point, or gesture to make a request"}
          </p>
        </div>
        <form
          className="session-actions"
          onSubmit={(event) => {
            event.preventDefault();
            void run(async () => {
              await api.startTrial(session.session_id, { instruction: instruction.trim() || "Live interaction" });
              setInstruction("");
            });
          }}
        >
          <input
            className="input"
            placeholder="Trial instruction (optional)"
            value={instruction}
            onChange={(event) => setInstruction(event.target.value)}
            aria-label="Trial instruction"
          />
          <button type="submit" className="btn btn-primary" disabled={busy}>
            New trial
          </button>
          <button type="button" className="btn" disabled={busy} onClick={() => run(() => api.stopSession(session.session_id))}>
            End session
          </button>
        </form>
      </div>
      {message ? <p className="error">{message}</p> : null}
    </section>
  );
}

/* ───────────────────────── Pipeline ───────────────────────── */

type Step = { label: string; value: string; detail: string; tone: Tone; active: boolean };

function pipeline(snapshot: LiveState | null): Step[] {
  const audio = snapshot?.audio;
  const vision = snapshot?.vision;
  const emg = snapshot?.features?.emg;
  const intent = snapshot?.intent;
  const safety = snapshot?.safety;
  const machine = snapshot?.machine;
  const pointed = vision?.pointing_candidates?.[0];
  const verdict = safety?.verdict ? VERDICT_COPY[safety.verdict] : undefined;
  const name = (id?: string | null) => objectName(id, vision?.objects);
  const busyMachine = machine?.state && machine.state !== "READY";

  return [
    {
      label: "Heard",
      value: audio?.transcript?.trim() ? `“${audio.transcript.trim()}”` : "Listening…",
      detail: audio?.action
        ? `${words(audio.action)}${audio.target_object_id ? ` · ${name(audio.target_object_id)}` : ""}`
        : "No request yet",
      tone: serviceTone(service(snapshot, "audio")),
      active: Boolean(audio?.transcript?.trim()),
    },
    {
      label: "Seen",
      value: pointed ? name(pointed.object_id) : `${vision?.objects?.length ?? 0} objects`,
      detail: pointed ? `Pointing · ${percent(pointed.confidence)}` : "No pointing target",
      tone: serviceTone(service(snapshot, "vision")),
      active: Boolean(pointed),
    },
    {
      label: "Gesture",
      value: words(emg?.label, "—"),
      detail: emg ? (emg.shadow_only ? "Monitoring only" : `${percent(emg.confidence)} · drives confirm/cancel`) : "No EMG model",
      tone: signalTone(snapshot?.biosignals?.emg),
      active: Boolean(emg && emg.label !== "rest" && !emg.shadow_only),
    },
    {
      label: "Decision",
      value: intent ? `${words(intent.action)}${intent.target_object_id ? ` · ${name(intent.target_object_id)}` : ""}` : "—",
      detail: intent ? `${percent(intent.confidence)} confidence` : "Waiting for evidence",
      tone: serviceTone(service(snapshot, "fusion")),
      active: Boolean(intent),
    },
    {
      label: "Safety",
      value: verdict?.label ?? "—",
      detail: verdict?.detail ?? "Nothing to check",
      tone: verdict?.tone ?? serviceTone(service(snapshot, "safety")),
      active: Boolean(verdict),
    },
    {
      label: "Machine",
      value: words(machine?.state, "No state yet"),
      detail: machine?.stage ? words(machine.stage) : machine?.fault_reason ?? "Idle",
      tone: machine?.state === "FAULT" || machine?.state === "ESTOPPED" ? "offline" : serviceTone(service(snapshot, "simulator")),
      active: Boolean(busyMachine),
    },
  ];
}

function Pipeline({ snapshot }: { snapshot: LiveState | null }) {
  return (
    <ol className="pipeline" aria-label="Signal to action pipeline">
      {pipeline(snapshot).map((step) => (
        <li key={step.label} className={`pipe-step tone-${step.tone}${step.active ? " active" : ""}`}>
          <span className="pipe-label">
            <i aria-hidden="true" />
            {step.label}
          </span>
          <strong title={step.value}>{step.value}</strong>
          <small>{step.detail}</small>
        </li>
      ))}
    </ol>
  );
}

/* ───────────────────────── Camera ───────────────────────── */

function CameraView({ vision, preview }: { vision: VisionState | null; preview: LiveState["vision_preview"] }) {
  const objects = vision?.objects ?? [];
  const pointed = vision?.pointing_candidates?.[0]?.object_id;
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
    <section className="card camera-card" aria-labelledby="camera-heading">
      <header className="card-head">
        <h2 id="camera-heading">Workspace camera</h2>
        <span className="muted">
          {objects.length} object{objects.length === 1 ? "" : "s"}
          {live ? "" : " · no video feed"}
        </span>
      </header>
      <div className="camera-stage">
        {live ? <img src={`${API_BASE}/api/vision/preview?t=${tick}`} alt="Live tabletop camera" width={width} height={height} /> : null}
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Detected objects">
          {!live ? <rect width={width} height={height} fill="#17191f" /> : null}
          {objects.map((object) => {
            const [x1, y1, x2, y2] = object.bbox_xyxy;
            const selected = object.object_id === pointed;
            return (
              <g key={object.object_id}>
                <rect
                  x={x1}
                  y={y1}
                  width={x2 - x1}
                  height={y2 - y1}
                  fill={selected ? "rgba(242,197,109,.18)" : "none"}
                  stroke={selected ? "#f2c56d" : "#ffffff"}
                  strokeWidth={selected ? 5 : 2}
                />
                <text x={x1 + 8} y={y1 + 24} fill="#ffffff" fontSize="18">
                  {words(object.class_name)} {percent(object.confidence)}
                </text>
              </g>
            );
          })}
        </svg>
        {!live && !objects.length ? <p className="camera-empty">Camera offline</p> : null}
      </div>
    </section>
  );
}

/* ───────────────────────── Decision ───────────────────────── */

function DecisionPanel({ snapshot }: { snapshot: LiveState | null }) {
  const intent = snapshot?.intent;
  const safety = snapshot?.safety;
  const verdict = safety?.verdict ? VERDICT_COPY[safety.verdict] : undefined;
  const name = (id?: string | null) => objectName(id, snapshot?.vision?.objects);
  const failed = Object.entries(safety?.checks ?? {}).filter(([, passed]) => passed === false);
  const passed = Object.entries(safety?.checks ?? {}).filter(([, ok]) => ok);

  return (
    <section className="card" aria-live="polite" aria-labelledby="decision-heading">
      <header className="card-head">
        <h2 id="decision-heading">Why</h2>
        {verdict ? <StatusPill status={verdict.tone} label={verdict.label} /> : null}
      </header>
      {!intent ? (
        <p className="muted empty">
          No decision yet. Say something like “hand me the red block”, point at an object, or both.
        </p>
      ) : (
        <>
          <p className="decision-line">
            {words(intent.action)}
            {intent.target_object_id ? ` · ${name(intent.target_object_id)}` : ""}
            <span>{percent(intent.confidence)}</span>
          </p>
          <p className="muted">{verdict?.detail ?? "Evaluating…"}</p>

          <h3 className="sub">Evidence</h3>
          <div className="evidence">
            {(intent.evidence ?? []).length ? (
              (intent.evidence ?? []).map((item) => (
                <div className="evidence-row" key={item.event_id}>
                  <strong>{words(item.modality)}</strong>
                  <div className="evidence-bar">
                    <span style={{ width: `${Math.round(Math.max(0, Math.min(1, item.contribution)) * 100)}%` }} />
                  </div>
                  <small>{percent(item.contribution)}</small>
                </div>
              ))
            ) : (
              <p className="muted">No evidence attached.</p>
            )}
          </div>

          {failed.length ? (
            <>
              <h3 className="sub">Blocking checks</h3>
              <ul className="check-list">
                {failed.map(([key]) => (
                  <li key={key}>
                    <StatusPill status="offline" label={words(key)} />
                  </li>
                ))}
              </ul>
            </>
          ) : null}

          {intent.conflicts?.length ? (
            <p className="callout">Conflict: {intent.conflicts.map((item) => words(item)).join(", ")}</p>
          ) : null}

          <details className="more">
            <summary>Technical detail</summary>
            <dl className="kv">
              <div><dt>Decision</dt><dd className="mono">{intent.decision_id}</dd></div>
              <div><dt>Fusion model</dt><dd>{intent.fusion_model_id ?? "—"}</dd></div>
              <div><dt>Policy</dt><dd>{safety?.policy_version ?? "—"}</dd></div>
              <div><dt>Passed checks</dt><dd>{passed.map(([key]) => words(key)).join(", ") || "—"}</dd></div>
              <div><dt>Reason codes</dt><dd>{safety?.reason_codes?.map((code) => words(code)).join(", ") || "—"}</dd></div>
              <div>
                <dt>Alternatives</dt>
                <dd>
                  {(intent.alternatives ?? [])
                    .map((alt) => `${words(alt.action)}${alt.target_object_id ? ` · ${name(alt.target_object_id)}` : ""} ${percent(alt.confidence)}`)
                    .join(", ") || "—"}
                </dd>
              </div>
            </dl>
          </details>
        </>
      )}
    </section>
  );
}

function Activity({ snapshot }: { snapshot: LiveState | null }) {
  const items = (snapshot?.timeline ?? []).slice(0, 8);
  return (
    <section className="card" aria-labelledby="activity-heading">
      <header className="card-head">
        <h2 id="activity-heading">Activity</h2>
      </header>
      {items.length ? (
        <ol className="activity">
          {items.map((item, index) => (
            <li key={`${item.t_ms}-${index}`}>
              <time>{clock(item.t_ms)}</time>
              <span className={`kind kind-${item.kind}`}>{words(item.kind)}</span>
              <strong>{words(item.label)}</strong>
            </li>
          ))}
        </ol>
      ) : (
        <p className="muted empty">Nothing yet.</p>
      )}
    </section>
  );
}

/* ───────────────────────── Diagnostics ───────────────────────── */

function SignalBlock({
  title,
  health,
  feature,
  plot,
}: {
  title: string;
  health?: BiosignalHealth;
  feature?: ModalityFeature | null;
  plot: PlotSnapshot;
}) {
  return (
    <article className="signal-block">
      <header className="card-head">
        <h3>{title}</h3>
        <StatusPill status={signalTone(health)} />
      </header>
      <p className="muted">
        {words(feature?.label, "No reading")} · quality {percent(health?.quality)} · {ago(health?.last_data_age_ms)}
      </p>
      <Sparkline plot={plot} label={`${title} channels`} />
      {health?.flags?.length ? <p className="muted">Flags: {health.flags.map((flag) => words(flag)).join(", ")}</p> : null}
    </article>
  );
}

function Diagnostics({ snapshot, plots }: { snapshot: LiveState | null; plots: { eeg: PlotSnapshot; emg: PlotSnapshot } }) {
  const services = snapshot?.services ?? [];
  const unhealthy = services.filter((item) => item.status !== "healthy");
  return (
    <details className="card diagnostics">
      <summary>
        <span>Signals & services</span>
        <span className="muted">
          {unhealthy.length ? `${unhealthy.length} need attention` : `${services.length} healthy`}
        </span>
      </summary>
      <div className="diag-grid">
        <SignalBlock title="EMG · Ganglion" health={snapshot?.biosignals?.emg} feature={snapshot?.features?.emg} plot={plots.emg} />
        <SignalBlock title="EEG · Crown (monitor only)" health={snapshot?.biosignals?.eeg} feature={snapshot?.features?.eeg} plot={plots.eeg} />
        <div className="service-list">
          {services.map((item) => (
            <div className="service-row" key={item.id}>
              <StatusPill status={item.status} label={item.name} />
              <small title={item.recovery ?? item.detail ?? undefined}>
                {item.status === "healthy" ? ago(item.last_heartbeat_age_ms) : item.detail ?? item.recovery ?? ago(item.last_heartbeat_age_ms)}
              </small>
            </div>
          ))}
        </div>
      </div>
    </details>
  );
}

function MockTools() {
  const { busy, message, run } = useBusyAction();
  const [note, setNote] = useState<string | null>(null);
  const send = (scenario: DemoScenario) =>
    run(async () => {
      const result = await api.runDemo(scenario);
      setNote(`${words(scenario)} · ${result.events_injected} synthetic events injected`);
    });
  return (
    <details className="card diagnostics">
      <summary>
        <span>Synthetic test events</span>
        <span className="muted">mock stack only</span>
      </summary>
      <p className="muted">Injects recorded fixtures instead of real sensor data. Not available on the hardware stack.</p>
      <div className="btn-row">
        <button type="button" className="btn" disabled={busy} onClick={() => send("success")}>Clear request</button>
        <button type="button" className="btn" disabled={busy} onClick={() => send("conflict")}>Conflicting signals</button>
        <button type="button" className="btn" disabled={busy} onClick={() => send("cancel")}>Cancellation</button>
      </div>
      {note ? <p className="muted" role="status">{note}</p> : null}
      {message ? <p className="error">{message}</p> : null}
    </details>
  );
}

export default function OperatePage() {
  const { snapshot, plots, connected } = useLive();
  return (
    <div className="operate">
      {!connected ? (
        <p className="banner banner-bad" role="status">
          Console API unreachable. Start the stack with <code>just run-hardware</code>; values below may be stale.
        </p>
      ) : null}
      <SessionBar snapshot={snapshot} />
      <Pipeline snapshot={snapshot} />
      <div className="operate-grid">
        <CameraView vision={snapshot?.vision ?? null} preview={snapshot?.vision_preview} />
        <div className="operate-side">
          <DecisionPanel snapshot={snapshot} />
          <Activity snapshot={snapshot} />
        </div>
      </div>
      <Diagnostics snapshot={snapshot} plots={plots} />
      {snapshot?.mock ? <MockTools /> : null}
    </div>
  );
}
