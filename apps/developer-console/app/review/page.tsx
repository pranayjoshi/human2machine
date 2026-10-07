"use client";

import { useEffect, useState } from "react";

import { StatusPill } from "@/components/Status";
import { api } from "@/lib/api";
import { useBusyAction } from "@/lib/live";
import type { SessionRecord } from "@/lib/types";

function shortId(value: string): string {
  return value.replace(/^session_/, "").slice(0, 8);
}

function words(value: string | null | undefined): string {
  if (!value) return "—";
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export default function ReviewPage() {
  const [sessions, setSessions] = useState<SessionRecord[]>([]);
  const [selected, setSelected] = useState<SessionRecord | null>(null);
  const { busy, message, run } = useBusyAction();

  useEffect(() => {
    void api.sessions().then((body) => setSessions(body.sessions)).catch(() => undefined);
  }, []);

  return (
    <>
      <header className="page-header">
        <div>
          <p className="eyebrow">Recorded work</p>
          <h1>Sessions</h1>
          <p className="lede">Review what was requested, what the system understood, and how each interaction ended.</p>
        </div>
        <span className="record-count">{sessions.length} recorded</span>
      </header>

      {message ? <p className="error">{message}</p> : null}

      <div className="session-review-layout">
        <section className="panel session-list">
          <div className="section-heading">
            <div>
              <p className="eyebrow">History</p>
              <h2>Recent sessions</h2>
            </div>
          </div>
          {sessions.length ? (
            sessions.map((session) => (
              <button
                type="button"
                className={selected?.session_id === session.session_id ? "selected" : ""}
                key={session.session_id}
                disabled={busy}
                onClick={() => run(async () => setSelected(await api.session(session.session_id)))}
              >
                <span className="session-id">{shortId(session.session_id)}</span>
                <span>
                  <strong>{session.started_at_ms ? new Date(session.started_at_ms).toLocaleDateString() : "Undated session"}</strong>
                  <small>
                    {session.started_at_ms
                      ? new Date(session.started_at_ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
                      : "—"}
                    {" · "}
                    {session.trials?.length ?? 0} interactions
                  </small>
                </span>
                <StatusPill status={session.state === "FAILED" ? "offline" : "healthy"} label={words(session.state)} />
              </button>
            ))
          ) : (
            <p className="muted">Your completed sessions will appear here.</p>
          )}
        </section>

        <section className="panel session-detail">
          {selected ? (
            <>
              <div className="section-heading">
                <div>
                  <p className="eyebrow">Session {shortId(selected.session_id)}</p>
                  <h2>{selected.trials.length} interactions</h2>
                </div>
                <StatusPill status={selected.state === "FAILED" ? "offline" : "healthy"} label={words(selected.state)} />
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Request</th>
                      <th>Expected</th>
                      <th>Interpreted</th>
                      <th>Safety</th>
                      <th>Outcome</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selected.trials.map((trial) => (
                      <tr key={trial.trial_id}>
                        <td>{trial.instruction ?? "Live interaction"}</td>
                        <td>{words(trial.ground_truth_target ?? trial.ground_truth_action)}</td>
                        <td>
                          {words(trial.prediction_action)}
                          {trial.prediction_target ? ` · ${words(trial.prediction_target)}` : ""}
                          {trial.prediction_confidence != null
                            ? ` · ${Math.round(trial.prediction_confidence * 100)}%`
                            : ""}
                        </td>
                        <td>{words(trial.verdict)}</td>
                        <td>{words(trial.outcome ?? trial.state)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <div className="session-empty">
              <p className="eyebrow">Session detail</p>
              <h2>Select a session.</h2>
              <p>Its decisions and outcomes will appear here.</p>
            </div>
          )}
        </section>
      </div>
    </>
  );
}
