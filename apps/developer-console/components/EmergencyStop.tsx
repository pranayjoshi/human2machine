"use client";

import { useState } from "react";

import { api } from "@/lib/api";
import { useBusyAction } from "@/lib/live";

export function EmergencyStop({ latched }: { latched: boolean }) {
  const { busy, message, run } = useBusyAction();
  const [resetOpen, setResetOpen] = useState(false);

  return (
    <div>
      <button
        type="button"
        className="btn btn-danger"
        aria-label="Emergency stop. Immediately request a STOP intent."
        onClick={() => run(() => api.estop())}
        disabled={busy}
      >
        Stop
      </button>
      {latched ? (
        <button
          type="button"
          className="btn"
          style={{ marginLeft: "0.5rem" }}
          onClick={() => setResetOpen(true)}
        >
          Reset…
        </button>
      ) : null}
      {message ? <p className="error">{message}</p> : null}
      {resetOpen ? (
        <div className="dialog-backdrop" role="presentation">
          <div
            className="dialog estop-reset"
            role="dialog"
            aria-modal="true"
            aria-labelledby="reset-title"
          >
            <p className="eyebrow">Safety latch</p>
            <h2 id="reset-title">Clear the stop?</h2>
            <p>Only continue after you have checked that the workspace is safe.</p>
            <div className="btn-row">
              <button
                type="button"
                className="btn btn-danger"
                onClick={() =>
                  run(async () => {
                    await api.reset();
                    setResetOpen(false);
                  })
                }
              >
                Clear stop
              </button>
              <button type="button" className="btn" onClick={() => setResetOpen(false)}>
                Keep stopped
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
