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
  if (tone === "healthy" || tone === "APPROVE") {
    return (
      <svg className="icon" viewBox="0 0 16 16" aria-hidden="true">
        <path fill="currentColor" d="M6.2 11.2 2.8 7.8l1.4-1.4 2 2 5-5 1.4 1.4z" />
      </svg>
    );
  }
  if (tone === "degraded" || tone === "HOLD" || tone === "ASK_CONFIRMATION") {
    return (
      <svg className="icon" viewBox="0 0 16 16" aria-hidden="true">
        <path fill="currentColor" d="M7 3h2v7H7zm0 8h2v2H7z" />
      </svg>
    );
  }
  return (
    <svg className="icon" viewBox="0 0 16 16" aria-hidden="true">
      <path fill="currentColor" d="M4.2 3 3 4.2 6.8 8 3 11.8 4.2 13 8 9.2 11.8 13 13 11.8 9.2 8 13 4.2 11.8 3 8 6.8z" />
    </svg>
  );
}

export function StatusPill({ status, label }: { status: Tone; label?: string }) {
  return (
    <span className="status-pill">
      <Icon tone={status} />
      <span>{label ?? LABELS[status] ?? status}</span>
    </span>
  );
}
