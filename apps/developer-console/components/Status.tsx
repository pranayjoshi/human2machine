type Tone = "healthy" | "degraded" | "offline" | string;

const LABELS: Record<string, string> = {
  healthy: "Healthy",
  degraded: "Degraded",
  offline: "Offline",
  APPROVE: "Approved",
  ASK_CONFIRMATION: "Confirmation required",
  HOLD: "Holding",
  REJECT: "Rejected",
  EMERGENCY_STOP: "Emergency stop",
};

function Icon({ tone }: { tone: Tone }) {
  return <span className={`status-mark ${String(tone).toLowerCase()}`} aria-hidden="true" />;
}

export function StatusPill({ status, label }: { status: Tone; label?: string }) {
  return (
    <span className="status-pill">
      <Icon tone={status} />
      <span>{label ?? LABELS[status] ?? status}</span>
    </span>
  );
}
