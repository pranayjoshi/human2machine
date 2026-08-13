import type {
  ControlResult,
  DemoRunResult,
  DemoScenario,
  EmgCalibrationStatus,
  PreflightResult,
  PublicConfig,
  SessionRecord,
  SetupStatus,
} from "./types";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

export function liveSocketUrl(): string {
  const url = new URL(API_BASE);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = "/api/live";
  url.search = "";
  return url.toString();
}

async function parse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

export async function apiGet<T>(path: string): Promise<T> {
  return parse<T>(await fetch(`${API_BASE}${path}`, { cache: "no-store" }));
}

export async function apiPost<T>(path: string, body: unknown = {}): Promise<T> {
  return parse<T>(
    await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}

export const api = {
  health: () => apiGet<{ status: string; mock: boolean }>("/api/health"),
  services: () => apiGet<{ services: unknown[] }>("/api/services"),
  config: () => apiGet<PublicConfig>("/api/config/public"),
  preflight: () => apiPost<PreflightResult>("/api/preflight"),
  startSession: (body: {
    user_id?: string;
    record_audio?: boolean;
    record_video?: boolean;
    consent?: boolean;
  }) => apiPost<ControlResult>("/api/sessions", body),
  stopSession: (id: string) => apiPost<ControlResult>(`/api/sessions/${id}/stop`),
  startTrial: (
    sessionId: string,
    body: {
      instruction: string;
      ground_truth_action?: string | null;
      ground_truth_target?: string | null;
      ambiguous?: boolean;
    },
  ) => apiPost<ControlResult>(`/api/sessions/${sessionId}/trials`, body),
  labelTrial: (trialId: string, body: Record<string, unknown>) =>
    apiPost<{ ok: boolean }>(`/api/trials/${trialId}/label`, body),
  confirm: (id: string) => apiPost<{ ok: boolean }>(`/api/confirmations/${id}/confirm`),
  cancel: (id: string) => apiPost<{ ok: boolean }>(`/api/confirmations/${id}/cancel`),
  estop: () => apiPost<{ ok: boolean }>("/api/machine/estop"),
  reset: () => apiPost<{ ok: boolean }>("/api/machine/reset"),
  sessions: () => apiGet<{ sessions: SessionRecord[] }>("/api/sessions"),
  session: (id: string) => apiGet<SessionRecord>(`/api/sessions/${id}`),
  replay: () => apiPost<{ ok: boolean; events_queued: number }>("/api/replay", { source: "fixtures" }),
  setup: () => apiGet<SetupStatus>("/api/setup"),
  runDemo: (scenario: DemoScenario) =>
    apiPost<DemoRunResult>("/api/demo/run", { scenario }),
  emgCalibrateStart: () => apiPost<EmgCalibrationStatus>("/api/calibrate/emg/start"),
  emgCalibrateStatus: () => apiGet<EmgCalibrationStatus>("/api/calibrate/emg/status"),
  emgCalibrateNext: () => apiPost<EmgCalibrationStatus>("/api/calibrate/emg/next"),
  emgCalibrateRecord: () => apiPost<EmgCalibrationStatus>("/api/calibrate/emg/record"),
  visionCalibrateComplete: () =>
    apiPost<{ ok: boolean; complete: boolean }>("/api/calibrate/vision/complete"),
  eegCalibrateAcknowledge: () =>
    apiPost<{ ok: boolean; shadow_only: boolean; drives_action: boolean }>(
      "/api/calibrate/eeg/acknowledge",
    ),
};
