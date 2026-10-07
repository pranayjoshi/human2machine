import { StatusPill } from "@/components/Status";
import type { IntentState, SafetyState } from "@/lib/types";

function words(value: string | null | undefined): string {
  if (!value) return "None";
  return value
    .replace(/^object_/, "")
    .replace(/_1$/, "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function percent(value: number | null | undefined): string {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}

function margin(intent: IntentState): number | null {
  const alternatives = intent.alternatives ?? [];
  if (!alternatives.length) return null;
  return intent.confidence - Math.max(...alternatives.map((item) => item.confidence));
}

function verdictCopy(verdict?: string): string {
  if (verdict === "APPROVE") return "The request passed every required safety check.";
  if (verdict === "ASK_CONFIRMATION") return "The request needs an explicit confirmation before it can continue.";
  if (verdict === "HOLD") return "The system is abstaining until clearer, fresher evidence arrives.";
  if (verdict === "REJECT") return "The safety policy blocked this request.";
  if (verdict === "EMERGENCY_STOP") return "Movement is stopped and the safety latch is active.";
  return "Waiting for the safety policy to evaluate this request.";
}

export function IntentInspector({
  intent,
  safety,
}: {
  intent: IntentState | null;
  safety: SafetyState | null;
}) {
  if (!intent) {
    return (
      <section className="empty-decision">
        <p className="eyebrow">No active decision</p>
        <h2>Waiting for a request.</h2>
        <p>Live evidence and the reason behind each decision will appear here.</p>
      </section>
    );
  }

  const target = intent.target_object_id ? words(intent.target_object_id) : null;
  const remaining = margin(intent);

  return (
    <div className="decision-layout">
      <section className="decision-hero">
        <p className="eyebrow">Interpreted request</p>
        <h2>
          {words(intent.action)}
          {target ? ` · ${target}` : ""}
        </h2>
        <p className="muted">{verdictCopy(safety?.verdict)}</p>
        <div className="decision-meta">
          <span>
            Confidence
            <strong>{percent(intent.confidence)}</strong>
          </span>
          <span>
            Status
            <strong>{words(intent.status ?? "PROPOSED")}</strong>
          </span>
          <span>
            Safety
            <strong>{words(safety?.verdict)}</strong>
          </span>
        </div>
      </section>

      <section className="panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Why</p>
            <h2>Evidence</h2>
          </div>
          <span className="muted">{intent.evidence?.length ?? 0} contributing signals</span>
        </div>
        <div className="evidence-list">
          {(intent.evidence ?? []).length ? (
            (intent.evidence ?? []).map((item) => (
              <div className="evidence-row" key={item.event_id}>
                <strong>{words(item.modality)}</strong>
                <div className="evidence-bar">
                  <span style={{ width: `${Math.round(Math.max(0, Math.min(1, item.contribution)) * 100)}%` }} />
                </div>
                <small>
                  {percent(item.contribution)} · quality {percent(item.quality)} · {Math.round(item.age_ms)} ms
                </small>
              </div>
            ))
          ) : (
            <p className="muted">No contributing evidence was attached.</p>
          )}
        </div>
      </section>

      <section className="panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Guardrails</p>
            <h2>Safety checks</h2>
          </div>
          {safety ? <StatusPill status={safety.verdict} /> : null}
        </div>
        <div className="safety-checks">
          {Object.entries(safety?.checks ?? {}).map(([key, passed]) => (
            <div key={key}>
              <StatusPill status={passed ? "healthy" : "offline"} label={words(key)} />
              <span>{passed ? "Passed" : "Blocked"}</span>
            </div>
          ))}
        </div>
        {!safety ? <p className="muted">No safety result is attached yet.</p> : null}
      </section>

      <details className="technical-details">
        <summary>Technical detail</summary>
        <dl className="kv">
          <div><dt>Decision ID</dt><dd>{intent.decision_id}</dd></div>
          <div><dt>Fusion model</dt><dd>{intent.fusion_model_id ?? "Unknown"}</dd></div>
          <div><dt>Fusion state</dt><dd>{words(intent.fusion_state)}</dd></div>
          <div><dt>Margin to next choice</dt><dd>{remaining == null ? "—" : percent(remaining)}</dd></div>
          <div><dt>Policy</dt><dd>{safety?.policy_version ?? "—"}</dd></div>
          <div><dt>Conflicts</dt><dd>{intent.conflicts?.map(words).join(", ") || "None"}</dd></div>
          <div><dt>Reason codes</dt><dd>{safety?.reason_codes?.map(words).join(", ") || "None"}</dd></div>
        </dl>
      </details>
    </div>
  );
}
