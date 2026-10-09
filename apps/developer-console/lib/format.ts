import type { BiosignalHealth, VisionObject } from "./types";

export type Tone = "healthy" | "degraded" | "offline";

/** "object_red_mug_1" -> "Red Mug", "REQUEST_HANDOFF" -> "Request Handoff". */
export function words(value: string | null | undefined, fallback = "—"): string {
  if (!value) return fallback;
  return value
    .replace(/^ExecutionStage\./, "")
    .replace(/^object_/, "")
    .replace(/_\d+$/, "")
    .replaceAll("_", " ")
    .toLowerCase()
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function percent(value: number | null | undefined): string {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}

export function ago(ms: number | null | undefined): string {
  if (ms == null) return "never";
  if (ms < 1000) return `${Math.round(ms)} ms ago`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s ago`;
  return `${Math.round(ms / 60_000)} min ago`;
}

export function clock(ms: number): string {
  return new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function elapsed(startedAt?: number | null, now = Date.now()): string {
  if (!startedAt) return "00:00";
  const total = Math.max(0, now - startedAt);
  const minutes = Math.floor(total / 60000);
  const seconds = Math.floor((total % 60000) / 1000);
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

export function signalTone(health?: BiosignalHealth): Tone {
  if (!health || health.last_data_age_ms == null || health.last_data_age_ms > 5000) return "offline";
  if ((health.quality ?? 0) < 0.4 || health.packet_loss_count > 0 || health.sequence_gaps > 0) {
    return "degraded";
  }
  return "healthy";
}

export const VERDICT_COPY: Record<string, { label: string; tone: Tone; detail: string }> = {
  APPROVE: { label: "Approved", tone: "healthy", detail: "Every required safety check passed." },
  ASK_CONFIRMATION: {
    label: "Needs your OK",
    tone: "degraded",
    detail: "Plausible, but not clear enough to act without confirmation.",
  },
  HOLD: { label: "Holding", tone: "degraded", detail: "Waiting for clearer or fresher evidence." },
  REJECT: { label: "Blocked", tone: "offline", detail: "The safety policy refused this request." },
  EMERGENCY_STOP: { label: "Stopped", tone: "offline", detail: "Emergency stop is latched." },
};

/** Human name for an object id, preferring the detector's class name. */
export function objectName(id: string | null | undefined, objects?: VisionObject[] | null): string {
  if (!id) return "—";
  const match = objects?.find((item) => item.object_id === id);
  return words(match?.class_name ?? id);
}
