"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { useBusyAction } from "@/lib/live";
import type { SetupStatus } from "@/lib/types";

const OBJECTS = [
  { id: "object_blue_1", label: "blue block" },
  { id: "object_red_1", label: "red block" },
  { id: "object_green_1", label: "green block" },
  { id: "object_yellow_1", label: "yellow block" },
];

export default function VisionCalibratePage() {
  const [setup, setSetup] = useState<SetupStatus | null>(null);
  const [complete, setComplete] = useState(false);
  const { busy, message, run } = useBusyAction();

  useEffect(() => {
    void api.setup().then(setSetup).catch(() => undefined);
  }, []);

  const cameraIndex = setup?.vision.camera_index ?? "unset";
  const ids = setup?.vision.object_ids ?? OBJECTS.map((item) => item.id);

  return (
    <>
      <h1>Vision calibration</h1>
      <p className="lede">
        This adapter reports objects, pointing, and coarse head direction. It does not claim
        eye-gaze tracking. A calibration saved at a different resolution must be redone.
      </p>
      <section className="panel">
        <h2>Camera</h2>
        <p>
          Index from <code>configs/local.yaml</code>: <strong>{String(cameraIndex)}</strong>
          {setup?.vision.width
            ? ` · ${setup.vision.width}×${setup.vision.height} @ ${setup.vision.fps} fps`
            : ""}
        </p>
        <p className="muted">
          Grant Camera permission to Terminal / VS Code. Close Zoom or Photo Booth if frames are
          black. Change the index on disk, not in this browser.
        </p>
      </section>
      <section className="panel" style={{ marginTop: "1rem" }}>
        <h2>Workspace</h2>
        <ol className="steps">
          <li>Fix the camera so the full table is visible.</li>
          <li>Mark table corners for workspace / homography calibration.</li>
          <li>Use consistent lighting. Avoid capturing other people in the background.</li>
        </ol>
      </section>
      <section className="panel" style={{ marginTop: "1rem" }}>
        <h2>Four object IDs</h2>
        <ul>
          {OBJECTS.map((item) => (
            <li key={item.id}>
              <code>{item.id}</code> — {item.label}
              {ids.includes(item.id) ? "" : " (not in current config)"}
            </li>
          ))}
        </ul>
        <p className="muted">Prefer ArUco markers if color IDs swap under changing light.</p>
      </section>
      <section className="panel" style={{ marginTop: "1rem" }}>
        <h2>Pointing test</h2>
        <ol className="steps">
          <li>Point clearly at the blue block, then red, green, and yellow.</li>
          <li>Confirm the live session overlay lists the matching pointing candidate.</li>
          <li>If no candidate appears, hand confidence is below threshold — that is correct.</li>
        </ol>
      </section>
      {message ? <p className="error">{message}</p> : null}
      {complete ? (
        <p role="status">
          Acknowledgement recorded: vision calibration completed for this console-api process.
        </p>
      ) : (
        <div className="btn-row">
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy}
            onClick={() =>
              run(async () => {
                await api.visionCalibrateComplete();
                setComplete(true);
              })
            }
          >
            I completed calibration
          </button>
        </div>
      )}
    </>
  );
}
