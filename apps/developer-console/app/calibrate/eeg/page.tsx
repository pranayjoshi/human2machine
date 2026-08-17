"use client";

import { useEffect, useState } from "react";

import { StatusPill } from "@/components/Status";
import { api } from "@/lib/api";
import { useBusyAction, useLive } from "@/lib/live";
import type { SetupStatus } from "@/lib/types";

export default function EegCalibratePage() {
  const { snapshot } = useLive();
  const [setup, setSetup] = useState<SetupStatus | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const { busy, message, run } = useBusyAction();

  useEffect(() => {
    void api.setup().then(setSetup).catch(() => undefined);
  }, []);

  const crown = (snapshot?.services ?? []).find((item) => item.id === "crown-adapter");

  return (
    <>
      <h1>EEG calibration (shadow-only)</h1>
      <p className="lede callout-text" role="note">
        EEG is shadow-only and never drives action. Crown features cannot approve, confirm, or
        execute a machine command. Fusion weight for EEG stays at zero for the MVP.
      </p>
      <section className="panel">
        <h2>Crown connection</h2>
        {crown ? (
          <p>
            <StatusPill status={crown.status} /> {crown.name}
            {crown.required ? "" : " · optional"}
            <span className="muted">
              {" "}
              · last heartbeat age {crown.last_heartbeat_age_ms ?? "—"} ms
            </span>
          </p>
        ) : (
          <p className="muted">Waiting for live service status…</p>
        )}
        <p>
          OSC path:{" "}
          {setup ? (setup.crown.env_vars_present ? "ready (UDP 9000)" : "not ready") : "…"}
        </p>
        <p className="muted">
          Put the Crown and this Mac on the same Wi-Fi. Enable OSC in the Neurosity console.
          BrainFlow listens on UDP 9000. Quality drops when the headset moves.
        </p>
      </section>
      <section className="panel" style={{ marginTop: "1rem" }}>
        <h2>Motion artifacts</h2>
        <p>
          Jaw clench, blink, and walking the headset will degrade quality. That is expected. The
          adapter must flag degraded quality rather than inventing a clean epoch. Old samples are
          never replayed as live.
        </p>
        <p className="muted">
          Shadow experiment blocks can be recorded later. They still cannot change safety verdicts.
        </p>
      </section>
      <section className="panel" style={{ marginTop: "1rem" }} aria-labelledby="shadow-heading">
        <h2 id="shadow-heading">Shadow policy</h2>
        <p>
          <strong>EEG is shadow-only and never drives action.</strong>
        </p>
        <p className="muted">
          {setup?.eeg_shadow_only
            ? "Config confirms eeg_shadow_only=true."
            : "Config should keep eeg_shadow_only=true for the MVP."}
        </p>
      </section>
      {message ? <p className="error">{message}</p> : null}
      {acknowledged ? (
        <p role="status">Acknowledged: EEG remains shadow-only for this console-api process.</p>
      ) : (
        <div className="btn-row">
          <button
            type="button"
            className="btn"
            disabled={busy}
            onClick={() =>
              run(async () => {
                await api.eegCalibrateAcknowledge();
                setAcknowledged(true);
              })
            }
          >
            I understand EEG is shadow-only
          </button>
        </div>
      )}
    </>
  );
}
