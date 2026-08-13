"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { StatusPill } from "@/components/Status";
import { API_BASE, api } from "@/lib/api";
import type { SetupStatus } from "@/lib/types";

function ConfigFlag({ label, set }: { label: string; set: boolean }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>
        <StatusPill status={set ? "healthy" : "offline"} label={set ? "Set" : "Not set"} />
      </dd>
    </div>
  );
}

export default function SetupPage() {
  const [setup, setSetup] = useState<SetupStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void api
      .setup()
      .then(setSetup)
      .catch((err: Error) => setError(err.message));
  }, []);

  return (
    <>
      <h1>Device setup</h1>
      <p className="lede">
        Connect Crown, Ganglion, microphone, camera, and the robot simulator. This page summarizes{" "}
        <code>docs/multimodal-intent-compiler/03_DEVICE_CONNECTION.md</code>. Hardware is opt-in;
        the mock stack does not need any of this.
      </p>
      <div className="mode-banner simulator" role="status" style={{ display: "inline-block", marginBottom: "1rem" }}>
        Simulator mode — no physical robot armed
      </div>
      {error ? <p className="error">{error}</p> : null}
      {setup ? (
        <>
          <section className="panel callout" aria-labelledby="secrets-heading">
            <h2 id="secrets-heading">Secrets stay on disk</h2>
            <p>
              This browser never stores passwords, tokens, or emails. Edit ignored{" "}
              <code>.env.local</code> (Neurosity) and <code>configs/local.yaml</code> (serial port,
              camera index, mic name). Then restart the affected adapter.
            </p>
            <ul>
              {(setup.operator_notes ?? []).map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </section>
          <section className="panel" aria-labelledby="checklist-heading" style={{ marginTop: "1rem" }}>
            <h2 id="checklist-heading">Config keys (from GET /api/setup)</h2>
            <ul className="checklist">
              {(setup.checklist ?? []).map((item) => (
                <li key={item.id} className="check-item">
                  <div>
                    <StatusPill
                      status={item.configured ? "healthy" : "offline"}
                      label={item.configured ? "Configured" : "Missing"}
                    />
                    <div>
                      <strong>{item.name}</strong>
                    </div>
                  </div>
                  <div>{item.detail}</div>
                </li>
              ))}
            </ul>
            <dl className="kv" style={{ marginTop: "1rem" }}>
              <ConfigFlag label="Crown env vars present" set={setup.crown.env_vars_present} />
              <ConfigFlag label="Ganglion serial_port set" set={setup.ganglion.serial_port_set} />
              <ConfigFlag label="Audio device_name set" set={setup.audio.device_name_set} />
              <div>
                <dt>Camera index</dt>
                <dd>{setup.vision.camera_index ?? "unset"}</dd>
              </div>
              <div>
                <dt>EEG shadow-only</dt>
                <dd>{setup.eeg_shadow_only ? "yes — never drives action" : "unexpected"}</dd>
              </div>
              <div>
                <dt>Mock console-api</dt>
                <dd>{setup.mock ? "yes" : "no"}</dd>
              </div>
            </dl>
          </section>
          <div className="grid-2" style={{ marginTop: "1rem" }}>
            <section className="panel">
              <h2>Neurosity Crown</h2>
              <p>Charge, fit, same Wi-Fi as this Mac. Claim the device in the Neurosity console.</p>
              <p className="muted">
                Put <code>NEUROSITY_EMAIL</code>, secret, and <code>NEUROSITY_DEVICE_ID</code> in{" "}
                <code>.env.local</code> only. EEG is shadow-only.
              </p>
            </section>
            <section className="panel">
              <h2>OpenBCI Ganglion</h2>
              <p>Charge the approved battery before electrodes. Never wear it while charging.</p>
              <p className="muted">
                Discover the port with <code>python -m ganglion_adapter.main --hardware --list-devices</code>{" "}
                and set <code>devices.ganglion.serial_port</code>.
              </p>
            </section>
            <section className="panel">
              <h2>Microphone</h2>
              <p>
                Constrained vocabulary: give me / hand me / select / confirm / cancel / stop, plus
                named colors or deictic “that one”.
              </p>
              <p className="muted">
                List devices with ffmpeg or <code>python -m audio_adapter.main --hardware --list-devices</code>.
              </p>
            </section>
            <section className="panel">
              <h2>Camera</h2>
              <p>
                Frame the full table. Four objects: blue, red, green, yellow. Mark table corners.
                This adapter does not claim eye-gaze tracking.
              </p>
              <p className="muted">
                Object IDs: {(setup.vision.object_ids ?? []).join(", ")}. Camera index{" "}
                {setup.vision.camera_index ?? "unset"} at {setup.vision.width}×{setup.vision.height}.
              </p>
            </section>
            <section className="panel">
              <h2>Robot simulator</h2>
              <p>
                Always on for the MVP. Consumes only approved action commands on port 5557. There is
                no hidden toggle for the SO-ARM.
              </p>
              <p className="muted">Machine mode: {setup.machine_mode}</p>
            </section>
            <section className="panel">
              <h2>Ports</h2>
              <dl className="kv">
                {Object.entries(setup.ports).map(([name, value]) => (
                  <div key={name}>
                    <dt>{name}</dt>
                    <dd>{String(value)}</dd>
                  </div>
                ))}
              </dl>
            </section>
          </div>
          <p className="lede" style={{ marginTop: "1rem" }}>
            {(setup.links ?? []).map((link) => (
              <span key={link.path}>
                <a href={`${API_BASE}${link.url}`} target="_blank" rel="noreferrer">
                  {link.title}
                </a>{" "}
                (<code>{link.path}</code>){" · "}
              </span>
            ))}
            Guided calibration: <Link href="/calibrate">Calibration</Link>
          </p>
        </>
      ) : (
        <p className="muted">Loading setup checklist…</p>
      )}
    </>
  );
}
