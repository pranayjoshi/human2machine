"use client";

import { useEffect, useState } from "react";

import { Sparkline } from "@/components/Sparkline";
import { StatusPill } from "@/components/Status";
import { api } from "@/lib/api";
import { useBusyAction, useLive } from "@/lib/live";
import type { SetupStatus } from "@/lib/types";

export default function EegCalibratePage() {
  const { snapshot, plots } = useLive();
  const [setup, setSetup] = useState<SetupStatus | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const { busy, message, run } = useBusyAction();

  useEffect(() => {
    void api.setup().then(setSetup).catch(() => undefined);
  }, []);

  const crown = snapshot?.services?.find((item) => item.id === "crown-adapter");
  const health = snapshot?.biosignals?.eeg;
  const feature = snapshot?.features?.eeg;

  return (
    <>
      <header className="page-header">
        <div>
          <p className="eyebrow">Crown · signal quality</p>
          <h1>Find a clean baseline.</h1>
          <p className="lede">Fit the headset, stay still, and confirm that all channels remain stable.</p>
        </div>
        <StatusPill status={crown?.status ?? "offline"} />
      </header>

      <div className="grid-2">
        <section className="panel">
          <div className="section-heading">
            <div><p className="eyebrow">Live signal</p><h2>{feature?.label === "artifact" ? "Movement detected" : "Baseline"}</h2></div>
            <strong>{health?.quality == null ? "—" : `${Math.round(health.quality * 100)}%`}</strong>
          </div>
          <Sparkline plot={plots.eeg} label="Crown channels" />
          <dl className="kv">
            <div><dt>Connection</dt><dd>{crown?.status ?? "Waiting"}</dd></div>
            <div><dt>Sample rate</dt><dd>{health?.sample_rate_hz ?? "—"} Hz</dd></div>
            <div><dt>Packet loss</dt><dd>{health?.packet_loss_count ?? 0}</dd></div>
            <div><dt>Artifact confidence</dt><dd>{feature?.confidence == null ? "—" : `${Math.round(feature.confidence * 100)}%`}</dd></div>
          </dl>
        </section>

        <section className="panel">
          <p className="eyebrow">Quick check</p>
          <h2>Three quiet minutes</h2>
          <ol className="steps">
            <li>Seat every sensor firmly and comfortably.</li>
            <li>Relax your jaw, eyes, and shoulders.</li>
            <li>Watch for flat channels or repeated movement flags.</li>
            <li>Adjust the fit and repeat until the baseline is stable.</li>
          </ol>
          <p className="muted">EEG remains a quality monitor. It cannot approve or execute an action.</p>
        </section>
      </div>

      {message ? <p className="error">{message}</p> : null}
      <div className="btn-row">
        <button
          type="button"
          className={`btn ${acknowledged ? "" : "btn-primary"}`}
          disabled={busy || acknowledged || !setup}
          onClick={() =>
            run(async () => {
              await api.eegCalibrateAcknowledge();
              setAcknowledged(true);
            })
          }
        >
          {acknowledged ? "Baseline acknowledged" : "Use this baseline"}
        </button>
      </div>
    </>
  );
}
