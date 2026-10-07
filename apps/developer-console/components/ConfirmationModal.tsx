"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { ConfirmationState } from "@/lib/types";

export function ConfirmationModal({ confirmation }: { confirmation: ConfirmationState | null }) {
  const [now, setNow] = useState(() => Date.now());
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 200);
    return () => window.clearInterval(id);
  }, []);

  if (!confirmation) return null;
  const remainingMs = Math.max(0, confirmation.expires_at_ms - now);
  const expired = remainingMs <= 0;
  const readable = (value?: string | null) =>
    (value || "Unknown")
      .replace(/^object_/, "")
      .replace(/_1$/, "")
      .replaceAll("_", " ")
      .replace(/\b\w/g, (letter) => letter.toUpperCase());

  const act = async (kind: "confirm" | "cancel") => {
    setError(null);
    try {
      if (kind === "confirm") await api.confirm(confirmation.confirmation_id);
      else await api.cancel(confirmation.confirmation_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div className="dialog-backdrop" role="presentation">
      <div
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        onKeyDown={(event) => {
          if (event.key === "Escape") void act("cancel");
        }}
      >
        <p className="eyebrow">Confirmation</p>
        <h2 id="confirm-title">Is this what you meant?</h2>
        <p className="big-action">
          {readable(confirmation.action)} · {readable(confirmation.target_object_id)}
        </p>
        <p>The signals were plausible but not clear enough to act without you.</p>
        <p className="expiry" aria-live="polite">
          {expired ? "Expired" : `Expires in ${(remainingMs / 1000).toFixed(1)} seconds`}
        </p>
        {error ? <p className="error">{error}</p> : null}
        <div className="btn-row">
          <button type="button" className="btn btn-primary" disabled={expired} onClick={() => void act("confirm")}>
            Yes, continue
          </button>
          <button type="button" className="btn" onClick={() => void act("cancel")}>
            No, cancel
          </button>
        </div>
        <p className="muted">Press Escape to cancel.</p>
      </div>
    </div>
  );
}
