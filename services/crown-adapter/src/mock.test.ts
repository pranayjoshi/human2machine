import assert from "node:assert/strict";
import test from "node:test";

import {
  BiosignalChunkPayloadSchema,
  EventEnvelopeSchema,
  ModalityFeaturePayloadSchema,
} from "@intent/contracts";

import { CrownMockGenerator, SAMPLE_RATE_HZ, SAMPLES_PER_CHUNK } from "./mock.ts";
import { CROWN_CHANNELS } from "./quality.ts";
import { deviceMsToNs } from "./timestamps.ts";

function collect(motion: boolean, chunks = 20) {
  const gen = new CrownMockGenerator({ seed: 7, motion });
  const events = [];
  for (let i = 0; i < chunks; i += 1) {
    events.push(...gen.next());
  }
  return events;
}

test("mock EEG epochs preserve Crown shape", () => {
  const events = collect(false, 4);
  const eeg = events.filter((event) => event.event_type === "biosignal.chunk");
  assert.ok(eeg.length >= 4);
  for (const event of eeg) {
    const parsed = EventEnvelopeSchema.parse(event);
    const payload = BiosignalChunkPayloadSchema.parse(parsed.payload);
    assert.equal(parsed.modality, "eeg");
    assert.equal(payload.sample_rate_hz, SAMPLE_RATE_HZ);
    assert.equal(payload.channel_names.length, 8);
    assert.deepEqual(payload.channel_names, [...CROWN_CHANNELS]);
    assert.equal(payload.sample_count, SAMPLES_PER_CHUNK);
    assert.equal(payload.samples.length, 8);
    assert.ok(payload.samples.every((channel) => channel.length === SAMPLES_PER_CHUNK));
    assert.equal(payload.units, "microvolts");
    assert.equal("normalized_time_ns" in event, false);
  }
});

test("mock timestamps match exact ms-to-ns conversion", () => {
  const gen = new CrownMockGenerator({ seed: 7 });
  gen.next();
  const eeg = gen.next().find((event) => event.event_type === "biosignal.chunk");
  assert.ok(eeg);
  assert.equal(eeg.source_time_ns, deviceMsToNs(62));
});

test("quality on envelopes drops when motion artifacts are generated", () => {
  const quiet = collect(false, 8).filter((event) => event.event_type === "data.quality");
  const moving = collect(true, 8).filter((event) => event.event_type === "data.quality");
  const quietMean = quiet.reduce((sum, event) => sum + event.quality, 0) / quiet.length;
  const movingMean = moving.reduce((sum, event) => sum + event.quality, 0) / moving.length;
  assert.ok(movingMean < quietMean);
  assert.ok(moving.some((event) => (event.payload.flags as string[]).includes("motion_artifact")));
});

test("every mock event is a valid unnormalized envelope", () => {
  const events = collect(true, 20);
  assert.ok(events.some((event) => event.event_type === "device.status"));
  assert.ok(events.some((event) => event.event_type === "motion.chunk"));
  for (const event of events) {
    EventEnvelopeSchema.parse(event);
    assert.equal("normalized_time_ns" in event, false);
    assert.equal(typeof event.received_monotonic_ns, "number");
    assert.equal(Number.isInteger(event.sequence), true);
  }
  const features = events.filter((event) => event.event_type === "modality.feature");
  for (const event of features) {
    const payload = ModalityFeaturePayloadSchema.parse(event.payload);
    assert.equal(payload.shadow_only, true);
    assert.notEqual(payload.label, "confirm");
    assert.notEqual(payload.label, "cancel");
  }
});

test("seeded generator is reproducible", () => {
  const a = collect(true, 3).map((event) => event.event_type);
  const b = collect(true, 3).map((event) => event.event_type);
  assert.deepEqual(a, b);
});
