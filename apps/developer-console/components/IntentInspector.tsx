import { StatusPill } from "@/components/Status";
import type { IntentState, SafetyState } from "@/lib/types";

function margin(intent: IntentState): number | null {
  const alts = intent.alternatives ?? [];
  if (!alts.length) return null;
  const bestAlt = Math.max(...alts.map((item) => item.confidence));
  return intent.confidence - bestAlt;
}

export function IntentInspector({
  intent,
  safety,
}: {
  intent: IntentState | null;
  safety: SafetyState | null;
}) {
  if (!intent) {
    return <p className="muted">No intent decision yet. Start a session or replay fixtures.</p>;
  }
  const remaining = margin(intent);
  return (
    <div className="kv">
      <div>
        <dt>Action</dt>
        <dd>{intent.action}</dd>
      </div>
      <div>
        <dt>Target</dt>
        <dd>{intent.target_object_id ?? "none"}</dd>
      </div>
      <div>
        <dt>Confidence</dt>
        <dd>{intent.confidence.toFixed(2)}</dd>
      </div>
      <div>
        <dt>Status</dt>
        <dd>{intent.status ?? "PROPOSED"}</dd>
      </div>
      <div>
        <dt>Margin vs next</dt>
        <dd>{remaining === null ? "n/a" : remaining.toFixed(2)}</dd>
      </div>
      <div>
        <dt>Fusion</dt>
        <dd>
          {intent.fusion_model_id ?? "unknown"} / {intent.fusion_state ?? "—"}
        </dd>
      </div>
      <div>
        <dt>Conflicts</dt>
        <dd>{intent.conflicts?.length ? intent.conflicts.join(", ") : "none"}</dd>
      </div>
      <div>
        <dt>Reason codes</dt>
        <dd>{intent.reason_codes?.length ? intent.reason_codes.join(", ") : "none"}</dd>
      </div>
      <div>
        <dt>Evidence IDs</dt>
        <dd>{intent.evidence?.map((item) => item.event_id).join(", ") || "none"}</dd>
      </div>
      {(intent.evidence ?? []).map((item) => (
        <div key={item.event_id}>
          <dt>
            {item.modality} contribution
          </dt>
          <dd>
            {item.contribution.toFixed(2)} · quality {item.quality.toFixed(2)} · age {item.age_ms} ms
          </dd>
        </div>
      ))}
      {safety ? (
        <>
          <div>
            <dt>Safety verdict</dt>
            <dd>
              <StatusPill status={safety.verdict} />
            </dd>
          </div>
          <div>
            <dt>Policy</dt>
            <dd>{safety.policy_version ?? "—"}</dd>
          </div>
          {Object.entries(safety.checks ?? {}).map(([key, value]) => (
            <div key={key}>
              <dt>{key}</dt>
              <dd>{value ? "pass" : "fail"}</dd>
            </div>
          ))}
        </>
      ) : (
        <p className="muted">No safety decision attached yet.</p>
      )}
    </div>
  );
}
