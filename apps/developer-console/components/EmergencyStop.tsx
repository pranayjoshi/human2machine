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
        Emergency stop
      </button>
      {latched ? (
        <button
          type="button"
          className="btn"
          style={{ marginLeft: "0.5rem" }}
          onClick={() => setResetOpen(true)}
        >
          Reset stop latch…
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
            <h2 id="reset-title">Reset emergency stop?</h2>
            <p>
              This does not happen if the browser disconnects. Confirm only if the workspace is
              safe and you intend to clear the latch.
            </p>
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
                Yes, reset emergency stop
              </button>
              <button type="button" className="btn" onClick={() => setResetOpen(false)}>
                Keep latched
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
