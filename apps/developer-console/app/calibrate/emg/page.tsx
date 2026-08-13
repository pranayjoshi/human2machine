"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { useBusyAction } from "@/lib/live";
import type { EmgCalibrationStatus } from "@/lib/types";

const PHASE_ORDER = ["rest", "confirm", "cancel", "false_trigger", "complete"] as const;

export default function EmgCalibratePage() {
  const [status, setStatus] = useState<EmgCalibrationStatus | null>(null);
  const { busy, message, run } = useBusyAction();

  const refresh = () => run(async () => setStatus(await api.emgCalibrateStatus()));

  useEffect(() => {
    void api.emgCalibrateStatus().then(setStatus).catch(() => undefined);
  }, []);

  const phase = status?.phase ?? "idle";
  const count = status?.counts?.[phase] ?? 0;
  const target = status?.target_count ?? 0;
  const canRecord = phase === "confirm" || phase === "cancel" || phase === "rest";

  return (
    <>
      <h1>EMG calibration</h1>
      <p className="lede">
        Ganglion forearm gestures only. Map four channels (flexor, extensor, pronator, aux).{" "}
        <strong>EEG is not used here</strong> and does not label these blocks.
      </p>
      <section className="panel phase-banner" aria-live="polite">
        <p className="muted">Current phase</p>
        <p className="big-action">{phase}</p>
        <p>{status?.instruction ?? "Start the protocol when electrodes are seated."}</p>
        <p>
          Counts — rest {status?.counts?.rest ?? 0}
          {phase === "rest" && status?.target_seconds
            ? ` (target ${status.target_seconds}s)`
            : ""}
          , confirm {status?.counts?.confirm ?? 0} / 20, cancel {status?.counts?.cancel ?? 0} / 20
        </p>
        {target > 0 ? (
          <p>
            This block: {count} / {target}
          </p>
        ) : null}
      </section>
      <ol className="steps">
        <li>
          <strong>Rest 30s.</strong> Forearm relaxed. Do not flex or extend.
        </li>
        <li>
          <strong>Confirm ×20.</strong> Gentle wrist flexion. Comfortable, not maximal.
        </li>
        <li>
          <strong>Cancel ×20.</strong> Gentle wrist extension.
        </li>
        <li>
          <strong>False-trigger note.</strong> A 10-minute rest trial is required before trusting EMG
          in a live demo. This stub does not start a training job.
        </li>
      </ol>
      {message ? <p className="error">{message}</p> : null}
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
            Log repetition
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
        <button type="button" className="btn" disabled={busy} onClick={() => void refresh()}>
          Refresh status
        </button>
      </div>
      <p className="muted">
        Phase order: {PHASE_ORDER.join(" → ")}. Promoted models live under <code>models/emg/</code>{" "}
        after held-out metrics — never commit biometric recordings.
      </p>
    </>
  );
}
