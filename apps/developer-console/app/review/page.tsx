"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { useBusyAction } from "@/lib/live";
import type { SessionRecord } from "@/lib/types";

export default function ReviewPage() {
  const [sessions, setSessions] = useState<SessionRecord[]>([]);
  const [selected, setSelected] = useState<SessionRecord | null>(null);
  const { busy, message, run } = useBusyAction();

  const load = () =>
    run(async () => {
      const body = await api.sessions();
      setSessions(body.sessions);
    });

  useEffect(() => {
    void api.sessions().then((body) => setSessions(body.sessions)).catch(() => undefined);
  }, []);

  return (
    <>
      <h1>Session review</h1>
      <p className="lede">
        Minimal trial table for ground truth, prediction, safety verdict, and outcome. Full media
        scrubbing is not in this MVP.
      </p>
      {message ? <p className="error">{message}</p> : null}
      <div className="btn-row">
        <button type="button" className="btn" onClick={() => void load()} disabled={busy}>
          Refresh
        </button>
      </div>
      <div className="table-wrap panel" style={{ marginTop: "1rem" }}>
        <table>
          <thead>
            <tr>
              <th>Session</th>
              <th>State</th>
              <th>Trials</th>
              <th>Started</th>
            </tr>
          </thead>
          <tbody>
            {sessions.map((session) => (
              <tr key={session.session_id}>
                <td>
                  <button
                    type="button"
                    className="btn"
                    onClick={() =>
                      run(async () => setSelected(await api.session(session.session_id)))
                    }
                  >
                    {session.session_id}
                  </button>
                </td>
                <td>{session.state}</td>
                <td>{session.trials?.length ?? 0}</td>
                <td>{session.started_at_ms ? new Date(session.started_at_ms).toLocaleString() : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {selected ? (
        <section className="panel" style={{ marginTop: "1rem" }}>
          <h2>Trials in {selected.session_id}</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Trial</th>
                  <th>Instruction</th>
                  <th>Ground truth</th>
                  <th>Prediction</th>
                  <th>Verdict</th>
                  <th>Outcome</th>
                </tr>
              </thead>
              <tbody>
                {selected.trials.map((trial) => (
                  <tr key={trial.trial_id}>
                    <td>{trial.trial_id}</td>
                    <td>{trial.instruction ?? "—"}</td>
                    <td>
                      {trial.ground_truth_action ?? "—"} / {trial.ground_truth_target ?? "—"}
                    </td>
                    <td>
                      {trial.prediction_action ?? "—"} / {trial.prediction_target ?? "—"}
                    </td>
                    <td>{trial.verdict ?? "—"}</td>
                    <td>{trial.outcome ?? trial.state ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </>
  );
}
