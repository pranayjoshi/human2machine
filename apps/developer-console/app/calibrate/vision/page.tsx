"use client";

import { useEffect, useState } from "react";

import { StatusPill } from "@/components/Status";
import { API_BASE, api } from "@/lib/api";
import { useBusyAction, useLive } from "@/lib/live";
import type { SetupStatus } from "@/lib/types";

export default function VisionCalibratePage() {
  const { snapshot } = useLive();
  const [setup, setSetup] = useState<SetupStatus | null>(null);
  const [complete, setComplete] = useState(false);
  const [tick, setTick] = useState(0);
  const { busy, message, run } = useBusyAction();

  useEffect(() => {
    void api.setup().then(setSetup).catch(() => undefined);
    const id = window.setInterval(() => setTick((value) => value + 1), 500);
    return () => window.clearInterval(id);
  }, []);

  const vision = snapshot?.vision;
  const preview = snapshot?.vision_preview;
  const pointed = vision?.pointing_candidates?.[0];

  return (
    <>
      <header className="page-header">
        <div>
          <p className="eyebrow">Camera · workspace</p>
          <h1>Frame the interaction.</h1>
          <p className="lede">Keep the table stable, every object visible, and the pointing area unobstructed.</p>
        </div>
        <StatusPill status={preview?.available ? "healthy" : "offline"} label={preview?.available ? "Camera live" : "No preview"} />
      </header>

      <div className="live-grid">
        <section className="panel">
          <div className="camera">
            <div className="camera-stage">
              {preview?.available ? (
                <img
                  src={`${API_BASE}/api/vision/preview?t=${tick}`}
                  alt="Live calibration camera"
                  width={preview.width}
                  height={preview.height}
                />
              ) : null}
            </div>
          </div>
          <p className="camera-caption">
            {vision?.objects?.length ?? 0} objects visible
            {pointed ? ` · pointing toward ${pointed.object_id.replace(/^object_/, "").replace(/_1$/, "")}` : ""}
          </p>
        </section>

        <section className="panel">
          <p className="eyebrow">Alignment</p>
          <h2>Workspace check</h2>
          <ol className="steps">
            <li>Fix the camera so the full table stays in frame.</li>
            <li>Place the blue, red, green, and yellow objects apart.</li>
            <li>Point to each object and check that the target follows.</li>
            <li>Repeat after any camera or lighting change.</li>
          </ol>
          <dl className="kv">
            <div><dt>Camera</dt><dd>{setup?.vision.camera_index ?? "—"}</dd></div>
            <div><dt>Resolution</dt><dd>{setup?.vision.width ?? "—"} × {setup?.vision.height ?? "—"}</dd></div>
            <div><dt>Objects</dt><dd>{vision?.objects?.length ?? 0} / 4</dd></div>
            <div><dt>Pointing confidence</dt><dd>{pointed ? `${Math.round(pointed.confidence * 100)}%` : "—"}</dd></div>
          </dl>
        </section>
      </div>

      {message ? <p className="error">{message}</p> : null}
      <div className="btn-row">
        <button
          type="button"
          className={`btn ${complete ? "" : "btn-primary"}`}
          disabled={busy || complete}
          onClick={() =>
            run(async () => {
              await api.visionCalibrateComplete();
              setComplete(true);
            })
          }
        >
          {complete ? "Workspace saved" : "Use this workspace"}
        </button>
      </div>
    </>
  );
}
