export type ServiceStatus = "healthy" | "degraded" | "offline";

export type ServiceView = {
  id: string;
  name: string;
  required: boolean;
  status: ServiceStatus;
  last_heartbeat_age_ms: number | null;
  missed_heartbeats: number;
  uptime_seconds?: number | null;
  error_count: number;
  last_data_age_ms?: number | null;
  recovery?: string | null;
};

export type PreflightCheck = {
  id: string;
  name: string;
  required: boolean;
  status: ServiceStatus;
  last_event_age_ms: number | null;
  message: string;
  recovery: string | null;
};

export type PreflightResult = {
  ready: boolean;
  checks: PreflightCheck[];
};

export type PublicConfig = {
  machine_mode: string;
  mock: boolean;
  schema_version: string;
  producer_version: string;
  safety?: { mode?: string; confirmation_timeout_ms?: number; policy_version?: string };
  fusion?: { model_id?: string; eeg_shadow_only?: boolean };
  storage?: { record_audio?: boolean; record_video?: boolean };
};

export type TrialRecord = {
  trial_id: string;
  instruction?: string | null;
  ground_truth_action?: string | null;
  ground_truth_target?: string | null;
  ambiguous?: boolean;
  state?: string;
  prediction_action?: string | null;
  prediction_target?: string | null;
  prediction_confidence?: number | null;
  verdict?: string | null;
  reason_codes?: string[];
  outcome?: string | null;
  user_correction?: string | null;
  notes?: string | null;
};

export type SessionRecord = {
  session_id: string;
  state: string;
  user_id?: string;
  record_audio?: boolean;
  record_video?: boolean;
  started_at_ms?: number | null;
  stopped_at_ms?: number | null;
  trials: TrialRecord[];
};

export type VisionObject = {
  object_id: string;
  class_name: string;
  confidence: number;
  bbox_xyxy: number[];
  table_position_xy: number[];
};

export type TargetCandidate = {
  object_id: string;
  confidence: number;
};

export type VisionState = {
  frame_id?: number;
  objects?: VisionObject[];
  pointing_candidates?: TargetCandidate[];
  head_direction_candidates?: TargetCandidate[];
};

export type AudioState = {
  transcript?: string;
  is_final?: boolean;
  action?: string | null;
  target_object_id?: string | null;
  confidence?: number;
};

export type EvidenceItem = {
  event_id: string;
  modality: string;
  contribution: number;
  quality: number;
  age_ms: number;
};

export type IntentAlternative = {
  action?: string | null;
  target_object_id?: string | null;
  confidence: number;
};

export type IntentState = {
  decision_id: string;
  action: string;
  target_object_id?: string | null;
  confidence: number;
  status?: string;
  alternatives?: IntentAlternative[];
  evidence?: EvidenceItem[];
  fusion_model_id?: string;
  fusion_state?: string | null;
  expires_at_ns?: number;
  conflicts?: string[];
  reason_codes?: string[];
};

export type SafetyChecks = Record<string, boolean | undefined>;

export type SafetyState = {
  decision_id: string;
  verdict: string;
  reason_codes?: string[];
  policy_version?: string;
  checks?: SafetyChecks;
  command_id?: string | null;
  confirmation_id?: string | null;
};

export type MachineState = {
  state: string;
  previous_state?: string | null;
  target_object_id?: string | null;
  progress?: number;
  fault_reason?: string | null;
};

export type ConfirmationState = {
  confirmation_id: string;
  decision_id?: string;
  action?: string | null;
  target_object_id?: string | null;
  reason_codes?: string[];
  expires_at_ms: number;
  why: string;
};

export type TimelineItem = {
  t_ms: number;
  kind: string;
  label: string;
};

export type PlotSnapshot = {
  channel_names: string[];
  samples: Record<string, number[]>;
  t_ms: number[];
};

export type LiveState = {
  mock: boolean;
  machine_mode: string;
  estop_latched: boolean;
  session: SessionRecord | null;
  active_trial_id?: string | null;
  services: ServiceView[];
  vision: VisionState | null;
  audio: AudioState | null;
  intent: IntentState | null;
  safety: SafetyState | null;
  machine: MachineState | null;
  confirmation: ConfirmationState | null;
  timeline: TimelineItem[];
  eeg: PlotSnapshot;
  emg: PlotSnapshot;
  server_time_ms: number;
};

export type ControlResult = {
  ok: boolean;
  session_id?: string | null;
  trial_id?: string | null;
  state?: string;
  error?: string | null;
};

export const PLOT_CAP = 150;
