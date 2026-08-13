import assert from "node:assert/strict";
import test from "node:test";

import { BiosignalChunkPayloadSchema, EventEnvelopeSchema } from "@intent/contracts";

import { backoffMs, convertEpoch } from "./hardware.ts";
import { runCrownAdapter } from "./main.ts";
import type { CrownClient, CrownEpoch } from "./neurosityClient.ts";
import { memoryPublisher } from "./publisher.ts";
import { CROWN_CHANNELS } from "./quality.ts";

function fakeEpoch(startTime: number, fill: number): CrownEpoch {
  const data = Array.from({ length: 8 }, (_, ch) =>
    Array.from({ length: 16 }, (_, n) => fill + ch + n * 0.01),
  );
  return {
    data,
    info: {
      channelNames: [...CROWN_CHANNELS],
      samplingRate: 256,
      startTime,
    },
  };
}

function fakeClient(epochs: CrownEpoch[], accel = { x: 0.05, y: -0.02, z: 0.99 }): CrownClient & {
  loginCalls: number;
  disconnectCalls: number;
} {
  return {
    loginCalls: 0,
    disconnectCalls: 0,
    async login() {
      this.loginCalls += 1;
    },
    async *rawEpochs() {
      for (const epoch of epochs) {
        yield epoch;
      }
    },
    async *accelerometer() {
      yield accel;
    },
    async disconnect() {
      this.disconnectCalls += 1;
    },
  };
}

test("hardware path uses injected client samples, not the mock generator", async () => {
  const pub = memoryPublisher();
  const epoch = fakeEpoch(1000, 40);
  const client = fakeClient([epoch]);
  await runCrownAdapter(["--hardware", "--duration-ms", "250"], pub, client);

  assert.ok(client.loginCalls >= 1);
  assert.ok(client.disconnectCalls >= 1);

  const eeg = pub.events.filter((event) => event.event_type === "biosignal.chunk");
  assert.ok(eeg.length >= 1);
  const first = eeg[0];
  EventEnvelopeSchema.parse(first);
  const payload = BiosignalChunkPayloadSchema.parse(first.payload);
  assert.equal(payload.sample_rate_hz, 256);
  assert.equal(payload.samples.length, 8);
  assert.equal(payload.sample_count, 16);
  assert.deepEqual(payload.samples[0]?.slice(0, 3), epoch.data[0]?.slice(0, 3));
  assert.equal("normalized_time_ns" in first, false);

  const statuses = pub.events.filter((event) => event.event_type === "device.status");
  assert.ok(statuses.some((event) => event.payload.device_alias === "crown"));
  assert.equal(
    statuses.some((event) => event.payload.device_alias === "crown-mock"),
    false,
  );
  assert.ok(pub.events.some((event) => event.event_type === "motion.chunk"));
  assert.ok(pub.events.some((event) => event.event_type === "service.heartbeat"));
});

test("hardware conversion skips replayed epochs with the same device startTime", () => {
  const accel = { x: 0, y: 0, z: 1, magnitude: 1, hasSample: true };
  let sequence = 0;
  const opts = {
    sequence: () => {
      const value = sequence;
      sequence += 1;
      return value;
    },
    packetLossCount: 0,
    chunksEmitted: 0,
    motionArtifactThreshold: 0.8,
    expectedChannels: 8,
    expectedSamples: 16,
    sampleRateHz: 256,
    shadowOnly: true,
    clockOffsetNs: null as number | null,
  };
  const once = convertEpoch(fakeEpoch(5000, 1), accel, opts);
  assert.equal(once.rejected, false);
  assert.ok(once.events.some((event) => event.event_type === "biosignal.chunk"));
});

test("reconnect backoff is exponential and capped at 30s", () => {
  assert.equal(backoffMs(0, 30), 1000);
  assert.equal(backoffMs(1, 30), 2000);
  assert.equal(backoffMs(2, 30), 4000);
  assert.equal(backoffMs(10, 30), 30_000);
});
