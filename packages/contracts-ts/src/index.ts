import { z } from "zod";

export const SCHEMA_VERSION = "1.0.0";
export const PRODUCER_VERSION = "0.1.0";

export const ActionSchema = z.enum([
  "SELECT_OBJECT",
  "REQUEST_HANDOFF",
  "CONFIRM",
  "CANCEL",
  "STOP",
]);

export const TargetReferenceSchema = z.enum(["NAMED", "DEICTIC", "ORDINAL", "NONE"]);

export const EventTypeSchema = z.enum([
  "biosignal.chunk",
  "motion.chunk",
  "modality.feature",
  "vision.objects",
  "vision.hands",
  "vision.head_direction",
  "audio.intent_candidate",
  "intent.candidate_set",
  "intent.decision",
  "intent.conflict",
  "intent.timeout",
  "safety.decision",
  "machine.state",
  "action.outcome",
  "service.heartbeat",
  "device.status",
  "data.quality",
  "session.started",
  "session.stopped",
  "session.failed",
  "trial.started",
  "trial.instruction",
  "trial.label",
  "trial.completed",
  "trial.aborted",
]);

export const SafetyVerdictSchema = z.enum([
  "APPROVE",
  "ASK_CONFIRMATION",
  "HOLD",
  "REJECT",
  "EMERGENCY_STOP",
]);

export const MachineStateSchema = z.enum([
  "DISCONNECTED",
  "IDLE",
  "READY",
  "EXECUTING",
  "HOLDING",
  "COMPLETED",
  "CANCELLED",
  "FAULT",
  "ESTOPPED",
]);

export const SessionStateSchema = z.enum([
  "NO_SESSION",
  "PREFLIGHT",
  "READY",
  "RECORDING",
  "STOPPING",
  "FINALIZED",
  "FAILED",
]);

export const unitInterval = z.number().min(0).max(1);
export const nanoseconds = z.number().int().nonnegative();

export const EventEnvelopeSchema = z
  .object({
    schema_version: z.string().refine((value) => value.split(".")[0] === "1", {
      message: "unsupported schema major version",
    }),
    event_id: z.string().min(8),
    event_type: EventTypeSchema,
    source: z.string().min(1),
    modality: z.string().nullable().optional(),
    session_id: z.string().nullable().optional(),
    trial_id: z.string().nullable().optional(),
    sequence: z.number().int().nonnegative(),
    source_time_ns: nanoseconds.nullable().optional(),
    received_monotonic_ns: nanoseconds,
    normalized_time_ns: nanoseconds.nullable().optional(),
    quality: unitInterval.default(1),
    producer_version: z.string(),
    payload: z.record(z.unknown()).default({}),
  })
  .passthrough();

export const BiosignalChunkPayloadSchema = z.object({
  sample_rate_hz: z.number().positive(),
  channel_names: z.array(z.string()),
  sample_count: z.number().int().positive(),
  samples: z.array(z.array(z.number())),
  units: z.string().default("microvolts"),
  filters_applied: z.array(z.string()).default([]),
  packet_loss_count: z.number().int().nonnegative().default(0),
  clock_confidence: unitInterval.optional(),
  estimated_first_sample_ns: nanoseconds.nullable().optional(),
});

export const ModalityFeaturePayloadSchema = z.object({
  feature_name: z.string(),
  window_start_ns: nanoseconds,
  window_end_ns: nanoseconds,
  label: z.string(),
  confidence: unitInterval,
  candidate_scores: z.record(unitInterval).default({}),
  model_id: z.string(),
  shadow_only: z.boolean().default(false),
});

export const VisionObjectSchema = z.object({
  object_id: z.string(),
  class_name: z.string(),
  confidence: unitInterval,
  bbox_xyxy: z.tuple([z.number(), z.number(), z.number(), z.number()]),
  table_position_xy: z.tuple([z.number(), z.number()]),
});

export const TargetCandidateSchema = z.object({
  object_id: z.string(),
  confidence: unitInterval,
});

export const VisionObjectsPayloadSchema = z.object({
  frame_id: z.number().int().nonnegative(),
  objects: z.array(VisionObjectSchema).default([]),
  pointing_candidates: z.array(TargetCandidateSchema).default([]),
  head_direction_candidates: z.array(TargetCandidateSchema).default([]),
});

export const AudioIntentPayloadSchema = z.object({
  transcript: z.string(),
  is_final: z.boolean(),
  action: ActionSchema.nullable().optional(),
  target_reference: TargetReferenceSchema.default("NONE"),
  target_object_id: z.string().nullable().optional(),
  confidence: unitInterval,
  utterance_start_ns: nanoseconds,
  utterance_end_ns: nanoseconds,
  model_id: z.string(),
});

export const EvidenceItemSchema = z.object({
  event_id: z.string(),
  modality: z.string(),
  contribution: z.number(),
  quality: unitInterval,
  age_ms: z.number().nonnegative(),
});

export const IntentDecisionPayloadSchema = z.object({
  decision_id: z.string(),
  action: ActionSchema,
  target_object_id: z.string().nullable().optional(),
  confidence: unitInterval,
  status: z.string().default("PROPOSED"),
  alternatives: z
    .array(
      z.object({
        action: ActionSchema.nullable().optional(),
        target_object_id: z.string().nullable().optional(),
        confidence: unitInterval,
      }),
    )
    .default([]),
  evidence: z.array(EvidenceItemSchema).default([]),
  fusion_model_id: z.string(),
  fusion_state: z.string().nullable().optional(),
  expires_at_ns: nanoseconds,
  conflicts: z.array(z.string()).default([]),
  reason_codes: z.array(z.string()).default([]),
});

export const SafetyDecisionPayloadSchema = z.object({
  decision_id: z.string(),
  verdict: SafetyVerdictSchema,
  reason_codes: z.array(z.string()).default([]),
  policy_version: z.string(),
  checks: z
    .object({
      intent_fresh: z.boolean(),
      target_visible: z.boolean(),
      cancel_absent: z.boolean(),
      machine_ready: z.boolean(),
      session_active: z.boolean().optional(),
      schema_valid: z.boolean().optional(),
      no_unresolved_conflict: z.boolean().optional(),
      confirmation_satisfied: z.boolean().optional(),
      physical_robot_disarmed: z.boolean().optional(),
    })
    .passthrough(),
  command_id: z.string().nullable().optional(),
  confirmation_id: z.string().nullable().optional(),
});

export const ActionCommandSchema = z.object({
  schema_version: z.string(),
  command_id: z.string(),
  decision_id: z.string(),
  action: ActionSchema,
  target_object_id: z.string().nullable().optional(),
  issued_at_ns: nanoseconds,
  expires_at_ns: nanoseconds,
  safety_policy_version: z.string(),
  idempotency_key: z.string(),
});

export const ServiceHeartbeatPayloadSchema = z.object({
  status: z.enum(["healthy", "degraded", "offline"]),
  uptime_seconds: z.number().nonnegative(),
  last_data_age_ms: z.number().nullable().optional(),
  error_count: z.number().int().nonnegative().default(0),
});

export const ControlRequestSchema = z.object({
  method: z.enum([
    "session.start",
    "session.stop",
    "trial.start",
    "trial.complete",
    "trial.abort",
  ]),
  request_id: z.string(),
  session_id: z.string().nullable().optional(),
  trial_id: z.string().nullable().optional(),
  payload: z.record(z.unknown()).default({}),
});

export const ControlResponseSchema = z.object({
  ok: z.boolean(),
  request_id: z.string(),
  method: z.string(),
  session_id: z.string().nullable().optional(),
  trial_id: z.string().nullable().optional(),
  state: SessionStateSchema,
  error: z.string().nullable().optional(),
  payload: z.record(z.unknown()).default({}),
});

export type EventEnvelope = z.infer<typeof EventEnvelopeSchema>;
export type ActionCommand = z.infer<typeof ActionCommandSchema>;
export type IntentDecisionPayload = z.infer<typeof IntentDecisionPayloadSchema>;
export type SafetyDecisionPayload = z.infer<typeof SafetyDecisionPayloadSchema>;
export type AudioIntentPayload = z.infer<typeof AudioIntentPayloadSchema>;
export type VisionObjectsPayload = z.infer<typeof VisionObjectsPayloadSchema>;
