"use client";

import { useEffect, useState } from "react";

import { Sparkline } from "@/components/Sparkline";
import { api } from "@/lib/api";
import { useBusyAction, useLive } from "@/lib/live";
import type { EmgCalibrationStatus } from "@/lib/types";

const PHASE_ORDER = ["rest", "confirm", "cancel", "random", "train", "false_trigger", "complete"] as const;

function formatPct(value: number | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

export default function EmgCalibratePage() {
  const [status, setStatus] = useState<EmgCalibrationStatus | null>(null);
  const { busy, message, run } = useBusyAction();
  const { snapshot, plots } = useLive();
  const emgHealth = snapshot?.biosignals?.emg;

  const refresh = () => run(async () => setStatus(await api.emgCalibrateStatus()));

  useEffect(() => {
    void api.emgCalibrateStatus().then(setStatus).catch(() => undefined);
  }, []);

  useEffect(() => {
    const phase = status?.phase ?? "idle";
    if (phase === "idle" || phase === "complete") return;
    const id = window.setInterval(() => {
      void api.emgCalibrateStatus().then(setStatus).catch(() => undefined);
    }, 400);
    return () => window.clearInterval(id);
  }, [status?.phase]);

  const phase = status?.phase ?? "idle";
  const count = status?.counts?.[phase] ?? 0;
  const target = status?.target_count ?? 0;
  const canRecord = phase === "confirm" || phase === "cancel" || phase === "random";
  const balance = status?.class_balance ?? {};
  const matrix = status?.metrics?.held_out?.confusion_matrix;
  const quality = emgHealth?.quality;

  return (
    <>
      <h1>EMG calibration</h1>
      <p className="lede">
        Ganglion forearm gestures only. Map four channels (flexor, extensor, pronator, aux).{" "}
        <strong>EEG is not used here</strong> and does not label these blocks. A single classified
        window never becomes a gesture — live inference uses dwell, hysteresis, and a refractory
        period.
      </p>
      <section className="panel phase-banner" aria-live="polite">
        <p className="muted">Current phase</p>
        <p className="big-action">{phase}</p>
        <p>{status?.instruction ?? "Start the protocol when electrodes are seated."}</p>
        {phase === "random" && status?.prompt_label ? (
          <p className="big-action">Do {status.prompt_label}</p>
        ) : null}
        <p>
          Windows — rest {balance.rest ?? 0}, confirm {balance.confirm ?? 0}, cancel {balance.cancel ?? 0}
          {status?.window_count != null ? ` · total ${status.window_count}` : ""}
        </p>
        <p>
          Repetitions — confirm {status?.counts?.confirm ?? 0} / 20, cancel {status?.counts?.cancel ?? 0} /
          20, random {status?.counts?.random ?? 0} / 20
        </p>
        {phase === "rest" && status?.target_seconds ? (
          <p>
            Rest target {status.target_seconds}s
            {status.remaining_seconds != null ? ` · remaining ${status.remaining_seconds.toFixed(0)}s` : ""}
          </p>
        ) : null}
        {target > 0 ? (
          <p>
            This block: {count} / {target}
          </p>
        ) : null}
      </section>
      <div className="grid-2" style={{ marginTop: "1rem" }}>
        <section className="panel">
          <h2>Live quality</h2>
          <dl className="kv">
            <div>
              <dt>Quality</dt>
              <dd>{quality == null ? "—" : quality.toFixed(2)}</dd>
            </div>
            <div>
              <dt>Packet loss</dt>
              <dd>{emgHealth?.packet_loss_count ?? 0}</dd>
            </div>
            <div>
              <dt>Current model</dt>
              <dd>
                <code>{status?.current_model_id ?? status?.promoted_model_id ?? "emg-rms heuristic"}</code>
              </dd>
            </div>
          </dl>
          <Sparkline plot={plots.emg} label="EMG envelope (live)" />
          <p className="muted">
            Flat, clipping, or disconnected channels should drop quality and emit UNKNOWN — not a stale
            confirm.
          </p>
        </section>
        <section className="panel">
          <h2>Protocol</h2>
          <ol className="steps">
            <li>
              <strong>Rest 30s.</strong> Forearm relaxed.
            </li>
            <li>
              <strong>Confirm ×20.</strong> Gentle wrist flexion.
            </li>
            <li>
              <strong>Cancel ×20.</strong> Gentle wrist extension.
            </li>
            <li>
              <strong>Randomized block ×20.</strong> Follow the prompt. Held-out for training.
            </li>
            <li>
              <strong>Train</strong> logistic regression, LDA, and a small forest. Grouped by block.
            </li>
            <li>
              <strong>False-trigger rest.</strong> Measure false confirm/cancel over a rest trial.
            </li>
          </ol>
        </section>
      </div>
      {status?.metrics ? (
        <section className="panel" style={{ marginTop: "1rem" }}>
          <h2>Held-out metrics</h2>
          <p>
            Estimator <code>{status.metrics.estimator ?? "—"}</code> · split{" "}
            {status.metrics.split_method ?? "grouped_by_block"} · n_train {status.metrics.n_train ?? "—"} ·
            n_test {status.metrics.n_test ?? "—"}
          </p>
          <p>
            Cross-block balanced accuracy{" "}
            <strong>{formatPct(status.metrics.cross_block_balanced_accuracy)}</strong>
            {status.metrics.gates?.cross_block_balanced_accuracy != null
              ? ` (gate ${formatPct(status.metrics.gates.cross_block_balanced_accuracy)})`
              : ""}
            {status.metrics.passed_cross_block ? " · passed" : " · not passed"}
          </p>
          {status.metrics.cancel_latency_ms != null ? (
            <p>Cancel commit latency {status.metrics.cancel_latency_ms.toFixed(0)} ms (gate 500 ms)</p>
          ) : null}
          {status.candidate_model_id ? (
            <p>
              Candidate <code>{status.candidate_model_id}</code>
            </p>
          ) : null}
          {matrix ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Actual \\ predicted</th>
                    <th>rest</th>
                    <th>confirm</th>
                    <th>cancel</th>
                  </tr>
                </thead>
                <tbody>
                  {["rest", "confirm", "cancel"].map((actual) => (
                    <tr key={actual}>
                      <th>{actual}</th>
                      <td>{matrix[actual]?.rest ?? 0}</td>
                      <td>{matrix[actual]?.confirm ?? 0}</td>
                      <td>{matrix[actual]?.cancel ?? 0}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </section>
      ) : null}
      {status?.false_trigger ? (
        <section className="panel" style={{ marginTop: "1rem" }}>
          <h2>False-trigger rest trial</h2>
          <p>
            {status.false_trigger.duration_s?.toFixed(0)} s · {status.false_trigger.n_windows} windows ·
            false confirm {status.false_trigger.false_confirm_per_10min?.toFixed(2)} / 10 min · false
            cancel {status.false_trigger.false_cancel_per_10min?.toFixed(2)} / 10 min
          </p>
          <p className="muted">
            Commits: confirm {status.false_trigger.confirm_commits ?? 0}, cancel{" "}
            {status.false_trigger.cancel_commits ?? 0}. Do not promote on accuracy alone.
          </p>
        </section>
      ) : null}
      {message ? <p className="error">{message}</p> : null}
      {status?.train_error ? <p className="error">{status.train_error}</p> : null}
      <div className="btn-row">
        <button
          type="button"
          className="btn btn-primary"
          disabled={busy}
          onClick={() => run(async () => setStatus(await api.emgCalibrateStart()))}
        >
          Start protocol
        </button>
        {canRecord ? (
          <button
            type="button"
            className="btn"
            disabled={busy}
            onClick={() => run(async () => setStatus(await api.emgCalibrateRecord()))}
          >
            Record repetition
          </button>
        ) : null}
        <button
          type="button"
          className="btn"
          disabled={busy || phase === "complete"}
          onClick={() => run(async () => setStatus(await api.emgCalibrateNext()))}
        >
          Next phase
        </button>
        {phase === "train" || phase === "random" || phase === "cancel" ? (
          <button
            type="button"
            className="btn"
            disabled={busy}
            onClick={() => run(async () => setStatus(await api.emgCalibrateTrain()))}
          >
            Train model
          </button>
        ) : null}
        {phase === "false_trigger" || (status?.candidate_model_id && !status.false_trigger) ? (
          <button
            type="button"
            className="btn"
            disabled={busy || !status?.candidate_model_id}
            onClick={() => run(async () => setStatus(await api.emgCalibrateFalseTrigger()))}
          >
            Run false-trigger trial
          </button>
        ) : null}
        <button
          type="button"
          className="btn btn-primary"
          disabled={busy || !status?.can_promote}
          onClick={() => run(async () => setStatus(await api.emgCalibratePromote()))}
        >
          Promote model
        </button>
        <button type="button" className="btn" disabled={busy} onClick={() => void refresh()}>
          Refresh status
        </button>
      </div>
      <p className="muted">
        Phase order: {PHASE_ORDER.join(" → ")}. Promoted models live under <code>models/emg/</code> with{" "}
        <code>metadata.json</code> — never commit biometric recordings.
      </p>
    </>
  );
}
