import assert from "node:assert/strict";
import test from "node:test";

import { CROWN_CHANNELS, sanitizeSamples, scoreQuality } from "./quality.ts";

test("quality decreases under generated motion artifacts", () => {
  const samples = CROWN_CHANNELS.map(() => [1, 2, 3, 2, 1, 0, -1, 0, 1, 2, 3, 2, 1, 0, -1, 0]);
  const quiet = scoreQuality({
    samples,
    packetLossCount: 0,
    chunksSinceLoss: 10,
    motionMagnitude: 0.05,
    motionArtifactThreshold: 0.8,
  });
  const moving = scoreQuality({
    samples,
    packetLossCount: 0,
    chunksSinceLoss: 10,
    motionMagnitude: 2.4,
    motionArtifactThreshold: 0.8,
  });
  assert.ok(quiet.score > moving.score);
  assert.ok(moving.motion_penalty < quiet.motion_penalty);
  assert.ok(moving.flags.includes("motion_artifact"));
  assert.equal(quiet.flags.includes("motion_artifact"), false);
});

test("non-finite samples are sanitized and marked invalid", () => {
  const raw = [
    [1, 2, 3],
    [1, Number.NaN, 3],
    [1, 2, Number.POSITIVE_INFINITY],
    [0, 0, 0],
    [1, 2, 3],
    [1, 2, 3],
    [1, 2, 3],
    [1, 2, 3],
  ];
  const { samples, invalidChannels } = sanitizeSamples(raw);
  assert.deepEqual(invalidChannels, [1, 2]);
  assert.equal(samples[1][1], 0);
  assert.ok(samples[2].every((value) => Number.isFinite(value)));
});

test("flat and missing packets reduce channel/packet quality", () => {
  const flat = CROWN_CHANNELS.map(() => Array(16).fill(0));
  const scored = scoreQuality({
    samples: flat,
    packetLossCount: 4,
    chunksSinceLoss: 0,
    motionMagnitude: 0,
    motionArtifactThreshold: 0.8,
  });
  assert.ok(scored.score < 0.5);
  assert.ok(scored.channel_validity < 1);
  assert.ok(scored.flags.some((flag) => flag.startsWith("flat:")));
});
