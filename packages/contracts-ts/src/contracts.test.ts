import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import {
  ActionCommandSchema,
  AudioIntentPayloadSchema,
  EventEnvelopeSchema,
  IntentDecisionPayloadSchema,
  SafetyDecisionPayloadSchema,
  unitInterval,
} from "./index.ts";

const fixtureDir = join(
  dirname(fileURLToPath(import.meta.url)),
  "../../../data/fixtures/events",
);

function load(name: string): unknown {
  return JSON.parse(readFileSync(join(fixtureDir, name), "utf8"));
}

test("accepts Python-shaped audio intent fixture", () => {
  const event = EventEnvelopeSchema.parse(load("audio_intent.json"));
  AudioIntentPayloadSchema.parse(event.payload);
  assert.equal(event.event_type, "audio.intent_candidate");
});

test("accepts intent decision fixture", () => {
  const event = EventEnvelopeSchema.parse(load("intent_decision.json"));
  IntentDecisionPayloadSchema.parse(event.payload);
});

test("accepts safety decision fixture", () => {
  const event = EventEnvelopeSchema.parse(load("safety_decision.json"));
  SafetyDecisionPayloadSchema.parse(event.payload);
});

test("accepts action command fixture", () => {
  ActionCommandSchema.parse(load("action_command.json"));
});

test("rejects invalid probability", () => {
  assert.throws(() => unitInterval.parse(1.2));
});

test("rejects unknown schema major version", () => {
  const event = load("audio_intent.json") as { schema_version: string };
  event.schema_version = "2.0.0";
  assert.throws(() => EventEnvelopeSchema.parse(event));
});
