"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { StatusPill } from "@/components/Status";
import { api } from "@/lib/api";
import { useBusyAction } from "@/lib/live";
import type { PreflightResult } from "@/lib/types";

export default function PreflightPage() {
  const router = useRouter();
  const [result, setResult] = useState<PreflightResult | null>(null);
  const { busy, message, run } = useBusyAction();

  const refresh = () => run(async () => setResult(await api.preflight()));

  useEffect(() => {
    void api.preflight().then(setResult).catch(() => undefined);
    const id = window.setInterval(() => {
      void api.preflight().then(setResult).catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(id);
  }, []);

  const requiredReady = Boolean(result?.ready);

  return (
    <>
      <h1>Preflight</h1>
      <p className="lede">
        Required services must be healthy before a session can start. Crown EEG is optional and
        shadow-only — it never drives actions.
      </p>
      <ul className="checklist" aria-label="Preflight checklist">
        {(result?.checks ?? []).map((check) => (
          <li key={check.id} className="check-item">
            <div>
              <StatusPill status={check.status} />
              <div>
                <strong>{check.name}</strong>
                {check.required ? "" : " · optional"}
              </div>
            </div>
            <div>
              <div>{check.message}</div>
              <div className="check-meta">
                Last event age:{" "}
                {check.last_event_age_ms == null
                  ? "unknown"
                  : `${Math.round(check.last_event_age_ms)} ms`}
              </div>
              {check.recovery ? <div className="check-meta">Recovery: {check.recovery}</div> : null}
            </div>
          </li>
        ))}
      </ul>
      {message ? <p className="error">{message}</p> : null}
      {result && !result.ready ? (
        <p className="lede" role="status">
          Required checks failed. Follow in-app device instructions on{" "}
          <Link href="/setup">Setup</Link> (Crown, Ganglion, mic, camera, simulator). Edit{" "}
          <code>.env.local</code> and <code>configs/local.yaml</code> on disk — this
          browser never stores secrets.
        </p>
      ) : null}
      <div className="btn-row">
        <button type="button" className="btn" onClick={() => void refresh()} disabled={busy}>
          Recheck
        </button>
        <button
          type="button"
          className="btn btn-primary"
          disabled={!requiredReady || busy}
          aria-disabled={!requiredReady}
          onClick={() =>
            run(async () => {
              await api.startSession({ user_id: "primary", consent: true });
              router.push("/session");
            })
          }
        >
          Start session
        </button>
        <button
          type="button"
          className="btn"
          onClick={() => run(() => api.replay())}
          disabled={busy}
        >
          Load fixture events
        </button>
      </div>
    </>
  );
}
