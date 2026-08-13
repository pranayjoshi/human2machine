import assert from "node:assert/strict";
import test from "node:test";

import { deviceMsToNs, sampleIndexToDeviceMs } from "./timestamps.ts";

test("millisecond timestamp conversion is exact integer arithmetic", () => {
  assert.equal(deviceMsToNs(0), 0);
  assert.equal(deviceMsToNs(1), 1_000_000);
  assert.equal(deviceMsToNs(62), 62_000_000);
  assert.equal(deviceMsToNs(1000), 1_000_000_000);
  assert.equal(deviceMsToNs(123456789), 123456789 * 1_000_000);
  assert.equal(deviceMsToNs(1.9), 1_000_000);
  assert.equal(deviceMsToNs(256.2), 256_000_000);
});

test("sample index mapping uses integer milliseconds", () => {
  assert.equal(sampleIndexToDeviceMs(0, 256), 0);
  assert.equal(sampleIndexToDeviceMs(16, 256), 62);
  assert.equal(sampleIndexToDeviceMs(32, 256), 125);
  assert.equal(deviceMsToNs(sampleIndexToDeviceMs(16, 256)), 62_000_000);
});

test("rejects non-finite device timestamps", () => {
  assert.throws(() => deviceMsToNs(Number.NaN));
  assert.throws(() => deviceMsToNs(Number.POSITIVE_INFINITY));
});
