"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { StatusPill } from "@/components/Status";
import { API_BASE, api } from "@/lib/api";
import type { SetupStatus } from "@/lib/types";

const DEVICE_COPY: Record<string, { role: string; next: string }> = {
  crown: { role: "EEG quality and artifact monitoring", next: "Fit the headset and confirm clean channels." },
  ganglion: { role: "Forearm gesture recognition", next: "Connect four channels, then calibrate your gestures." },
  audio: { role: "Spoken request recognition", next: "Choose the microphone and speak a short command." },
  vision: { role: "Object and pointing detection", next: "Frame the table and keep all objects visible." },
  simulator: { role: "Safe machine outcome preview", next: "Runs locally; physical motion remains disabled." },
};

function keyFor(id: string): string {
  if (id.includes("crown")) return "crown";
  if (id.includes("ganglion")) return "ganglion";
  if (id.includes("audio")) return "audio";
  if (id.includes("vision")) return "vision";
  return "simulator";
}

export default function SetupPage() {
  const [setup, setSetup] = useState<SetupStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void api.setup().then(setSetup).catch((reason: Error) => setError(reason.message));
  }, []);

  return (
    <>
      <header className="page-header">
        <div>
          <p className="eyebrow">Hardware</p>
          <h1>Devices</h1>
          <p className="lede">A simple view of the sensors in the loop and what each one contributes.</p>
        </div>
        <Link className="btn btn-primary" href="/calibrate">Open calibration</Link>
      </header>

      {error ? <p className="error">{error}</p> : null}

      <div className="device-grid">
        {(setup?.checklist ?? []).map((item) => {
          const copy = DEVICE_COPY[keyFor(item.id)] ?? DEVICE_COPY.simulator;
          return (
            <article className="panel device-card" key={item.id}>
              <header>
                <span className="device-number">{String((setup?.checklist ?? []).indexOf(item) + 1).padStart(2, "0")}</span>
                <StatusPill status={item.configured ? "healthy" : "offline"} label={item.configured ? "Ready" : "Needs setup"} />
              </header>
              <h2>{item.name}</h2>
              <p>{copy.role}</p>
              <small>{item.configured ? item.detail : copy.next}</small>
            </article>
          );
        })}
      </div>

      {!setup ? <p className="muted">Checking device configuration…</p> : null}

      {setup ? (
        <details className="technical-details" style={{ marginTop: "14px" }}>
          <summary>Connection details</summary>
          <div className="setup-detail-grid">
            <dl className="kv">
              <div><dt>Mode</dt><dd>{setup.mock ? "Simulation" : "Live hardware"}</dd></div>
              <div><dt>Ganglion transport</dt><dd>{setup.ganglion.transport ?? "Not set"}</dd></div>
              <div><dt>Camera</dt><dd>{setup.vision.camera_index ?? "—"} · {setup.vision.width}×{setup.vision.height}</dd></div>
              <div><dt>Audio sample rate</dt><dd>{setup.audio.sample_rate_hz ?? "—"} Hz</dd></div>
              <div><dt>EEG control</dt><dd>{setup.eeg_shadow_only ? "Monitoring only" : "Review configuration"}</dd></div>
              <div><dt>EMG control</dt><dd>{setup.emg_shadow_only ? "Monitoring only" : "Enabled after calibration"}</dd></div>
            </dl>
            <div>
              <p className="eyebrow">Operator guide</p>
              {(setup.links ?? []).map((link) => (
                <a className="doc-link" key={link.path} href={`${API_BASE}${link.url}`} target="_blank" rel="noreferrer">
                  {link.title} →
                </a>
              ))}
            </div>
          </div>
        </details>
      ) : null}
    </>
  );
}
