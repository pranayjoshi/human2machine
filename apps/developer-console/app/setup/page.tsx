"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { StatusPill } from "@/components/Status";
import { API_BASE, api } from "@/lib/api";
import { ago, percent } from "@/lib/format";
import { useBusyAction, useLive } from "@/lib/live";
import type { EmgCalibrationStatus, PreflightResult, ServiceView, SetupStatus } from "@/lib/types";

const DEVICES: Record<string, { purpose: string; service: string; todo: string }> = {
  crown: { purpose: "EEG quality monitor (never commands the machine)", service: "crown", todo: "Fit the headset and enable OSC in the Neurosity app." },
  ganglion: { purpose: "Forearm gestures: confirm and cancel", service: "ganglion", todo: "Pair over BLE or set the USB dongle port in configs/local.yaml." },
  audio: { purpose: "Spoken requests (Parakeet speech recognition)", service: "audio", todo: "Choose a microphone in configs/local.yaml." },
  vision: { purpose: "Objects (YOLOE), pointing and head direction (MediaPipe)", service: "vision", todo: "Set camera_index and describe your objects in configs/modalities.yaml." },
  simulator: { purpose: "Executes approved commands", service: "simulator", todo: "Runs locally; physical motion stays disabled." },
};

function liveService(services: ServiceView[] | undefined, key: string): ServiceView | undefined {
  return services?.find((item) => item.id.includes(key));
}

export default function SetupPage() {
  const { snapshot } = useLive();
  const [setup, setSetup] = useState<SetupStatus | null>(null);
  const [emg, setEmg] = useState<EmgCalibrationStatus | null>(null);
  const [preflight, setPreflight] = useState<PreflightResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { busy, message, run } = useBusyAction();

  const check = useCallback(() => run(async () => setPreflight(await api.preflight())), [run]);

  useEffect(() => {
    void api.setup().then(setSetup).catch((reason: Error) => setError(reason.message));
    void api.emgCalibrateStatus().then(setEmg).catch(() => undefined);
    void check();
  }, [check]);

  const services = snapshot?.services;
  const audio = liveService(services, "audio");
  const emgModel = emg?.promoted_model_id ?? emg?.current_model_id ?? null;
  const required = preflight?.checks.filter((item) => item.required) ?? [];
  const readyCount = required.filter((item) => item.status === "healthy").length;

  return (
    <div className="setup">
      <header className="page-title">
        <div>
          <h1>Setup</h1>
          <p className="muted">Work top to bottom. Everything here reads live status from the running stack.</p>
        </div>
        <div className="btn-row">
          <span className={`chip ${preflight?.ready ? "chip-ok" : "chip-warn"}`}>
            <i aria-hidden="true" />
            {preflight ? `${readyCount}/${required.length} required ready` : "Checking…"}
          </span>
          <button type="button" className="btn" disabled={busy} onClick={() => void check()}>Run preflight</button>
          <Link className="btn btn-primary" href="/session">Go to Operate</Link>
        </div>
      </header>

      {error ? <p className="error">{error}</p> : null}
      {message ? <p className="error">{message}</p> : null}
      {setup?.mock ? (
        <p className="banner banner-warn">
          The stack is running with <code>--mock</code>: no real devices are connected. Restart with <code>just run-hardware</code>.
        </p>
      ) : null}

      <section className="card">
        <header className="card-head">
          <h2><span className="step-no">1</span>Devices</h2>
        </header>
        <div className="table-wrap">
          <table className="setup-table">
            <thead>
              <tr><th>Device</th><th>Role</th><th>Configured</th><th>Live</th></tr>
            </thead>
            <tbody>
              {(setup?.checklist ?? []).map((item) => {
                const copy = DEVICES[item.id] ?? DEVICES.simulator;
                const live = liveService(services, copy.service);
                return (
                  <tr key={item.id}>
                    <td><strong>{item.name}</strong></td>
                    <td className="muted">{copy.purpose}</td>
                    <td>
                      <StatusPill status={item.configured ? "healthy" : "offline"} label={item.configured ? "Yes" : "No"} />
                      <small className="cell-note">{item.configured ? item.detail : copy.todo}</small>
                    </td>
                    <td>
                      <StatusPill status={live?.status ?? "offline"} />
                      <small className="cell-note">
                        {live?.status === "healthy" ? ago(live.last_heartbeat_age_ms) : live?.recovery ?? live?.detail ?? "Not running"}
                      </small>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {!setup ? <p className="muted">Reading configuration…</p> : null}
      </section>

      <section className="card">
        <header className="card-head">
          <h2><span className="step-no">2</span>Calibrate</h2>
        </header>
        <div className="cal-list">
          <Link className="cal-row" href="/calibrate/vision">
            <div>
              <strong>Camera workspace</strong>
              <span className="muted">Frame the table and check every object is detected.</span>
            </div>
            <span className="muted">{snapshot?.vision?.objects?.length ?? 0} objects visible</span>
            <span className="text-link">Open →</span>
          </Link>
          <Link className="cal-row" href="/calibrate/emg">
            <div>
              <strong>EMG gesture model</strong>
              <span className="muted">Record rest, confirm and cancel; train; check false triggers; promote.</span>
            </div>
            <StatusPill status={emgModel ? "healthy" : "offline"} label={emgModel ? "Model promoted" : "No model yet"} />
            <span className="text-link">Open →</span>
          </Link>
          <Link className="cal-row" href="/calibrate/eeg">
            <div>
              <strong>EEG signal quality</strong>
              <span className="muted">Confirm clean channels and recognise movement artifacts.</span>
            </div>
            <span className="muted">quality {percent(snapshot?.biosignals?.eeg?.quality)}</span>
            <span className="text-link">Open →</span>
          </Link>
        </div>
      </section>

      <section className="card">
        <header className="card-head">
          <h2><span className="step-no">3</span>Preflight</h2>
          <button type="button" className="btn" disabled={busy} onClick={() => void check()}>Re-run</button>
        </header>
        {preflight ? (
          <ul className="preflight">
            {preflight.checks.map((item) => (
              <li key={item.id}>
                <StatusPill status={item.status} label={item.name} />
                <span className="muted">{item.required ? "required" : "optional"}</span>
                <span>{item.status === "healthy" ? item.message : item.recovery ?? item.message}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">Running…</p>
        )}
      </section>

      {setup ? (
        <details className="card diagnostics">
          <summary><span>Connection details & docs</span></summary>
          <div className="setup-detail-grid">
            <dl className="kv">
              <div><dt>Mode</dt><dd>{setup.mock ? "Mock" : "Live hardware"}</dd></div>
              <div><dt>Speech recognition</dt><dd>{audio?.asr_backend ?? "—"}</dd></div>
              <div><dt>Ganglion transport</dt><dd>{setup.ganglion.transport ?? "Not set"}</dd></div>
              <div><dt>Camera</dt><dd>#{setup.vision.camera_index ?? "—"} · {setup.vision.width}×{setup.vision.height} @ {setup.vision.fps} fps</dd></div>
              <div><dt>Objects</dt><dd>{setup.vision.object_ids.join(", ") || "—"}</dd></div>
              <div><dt>EEG drives actions</dt><dd>{setup.eeg_shadow_only ? "No (monitor only)" : "Yes"}</dd></div>
              <div><dt>EMG drives actions</dt><dd>{setup.emg_shadow_only ? "No (shadow mode)" : "Yes"}</dd></div>
            </dl>
            <div className="doc-links">
              {(setup.links ?? []).map((link) => (
                <a className="text-link" key={link.path} href={`${API_BASE}${link.url}`} target="_blank" rel="noreferrer">
                  {link.title} →
                </a>
              ))}
            </div>
          </div>
        </details>
      ) : null}
    </div>
  );
}
