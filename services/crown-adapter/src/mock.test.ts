import assert from "node:assert/strict";
import test from "node:test";

import {
  BiosignalChunkPayloadSchema,
  EventEnvelopeSchema,
  ModalityFeaturePayloadSchema,
} from "@intent/contracts";

import { parseArgs } from "./main.ts";
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

test("disconnect emits degraded/offline then new live samples", () => {
  const gen = new CrownMockGenerator({ seed: 7 });
  const before = collectFrom(gen, 4);
  const eegBefore = before.filter((event) => event.event_type === "biosignal.chunk");
  const lastBefore = eegBefore[eegBefore.length - 1];
  assert.ok(lastBefore);
  assert.ok((lastBefore.source_time_ns ?? 0) > 0);
  const lastSeq = lastBefore.sequence;

  const disconnect = gen.simulateDisconnect();
  const statuses = disconnect
    .filter((event) => event.event_type === "device.status")
    .map((event) => event.payload.status);
  assert.deepEqual(statuses, ["degraded", "offline", "healthy"]);

  const after = gen.next();
  const eegAfter = after.find((event) => event.event_type === "biosignal.chunk");
  assert.ok(eegAfter);
  assert.equal(eegAfter.source_time_ns, deviceMsToNs(0));
  assert.ok(eegAfter.sequence > lastSeq + 1);
  assert.notEqual(eegAfter.event_id, lastBefore.event_id);
});

test("parseArgs accepts fast mode and disconnect-after-ms", () => {
  const opts = parseArgs(["--mock", "--fast", "--disconnect-after-ms", "250", "--duration-ms", "500"]);
  assert.equal(opts.mock, true);
  assert.equal(opts.fast, true);
  assert.equal(opts.disconnectAfterMs, 250);
  assert.equal(opts.durationMs, 500);
});

function collectFrom(gen: CrownMockGenerator, chunks: number) {
  const events = [];
  for (let i = 0; i < chunks; i += 1) {
    events.push(...gen.next());
  }
  return events;
}
