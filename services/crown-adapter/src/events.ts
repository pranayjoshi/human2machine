import { randomUUID } from "node:crypto";

import { PRODUCER_VERSION, SCHEMA_VERSION } from "@intent/contracts";

import { CROWN_CHANNELS } from "./quality.ts";
import { monotonicNs } from "./timestamps.ts";

export const SOURCE = "crown-adapter";

export type UnnormalizedEvent = {
  schema_version: string;
  event_id: string;
  event_type: string;
  source: string;
  modality: string | null;
  session_id: string | null;
  trial_id: string | null;
  sequence: number;
  source_time_ns: number | null;
  received_monotonic_ns: number;
  quality: number;
  producer_version: string;
  payload: Record<string, unknown>;
};

export function makeEvent(opts: {
  eventType: string;
  modality: string | null;
  sequence: number;
  sourceTimeNs: number | null;
  quality?: number;
  payload: Record<string, unknown>;
}): UnnormalizedEvent {
  return {
    schema_version: SCHEMA_VERSION,
    event_id: randomUUID().replaceAll("-", ""),
    event_type: opts.eventType,
    source: SOURCE,
    modality: opts.modality,
    session_id: null,
    trial_id: null,
    sequence: opts.sequence,
    source_time_ns: opts.sourceTimeNs,
    received_monotonic_ns: monotonicNs(),
    quality: opts.quality ?? 1,
    producer_version: PRODUCER_VERSION,
    payload: opts.payload,
  };
}

export function heartbeatEvent(
  sequence: number,
  uptimeSeconds: number,
  lastDataAgeMs: number | null,
  errorCount: number,
  status = "healthy",
): UnnormalizedEvent {
  return makeEvent({
    eventType: "service.heartbeat",
    modality: null,
    sequence,
    sourceTimeNs: null,
    payload: {
      status,
      uptime_seconds: uptimeSeconds,
      last_data_age_ms: lastDataAgeMs,
      error_count: errorCount,
    },
  });
}

export function deviceStatusEvent(
  sequence: number,
  status: "healthy" | "degraded" | "offline",
  detail: string | null,
  metadata: Record<string, unknown> = {},
): UnnormalizedEvent {
  return makeEvent({
    eventType: "device.status",
    modality: "eeg",
    sequence,
    sourceTimeNs: null,
    payload: {
      status,
      device_alias: "crown-mock",
      detail,
      battery_percent: 92,
      metadata: {
        stream: "raw",
        os_version: "mock",
        ...metadata,
      },
    },
  });
}

export { CROWN_CHANNELS };
