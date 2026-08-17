import assert from "node:assert/strict";
import test from "node:test";

import {
  deviceMatchesWanted,
  isTransientNeurosityAuthError,
  looksLikeNeurosityDeviceId,
  pickCrownDevice,
} from "./neurosityClient.ts";

test("nickname values are not treated as Neurosity device IDs", () => {
  assert.equal(looksLikeNeurosityDeviceId("crown-995"), false);
  assert.equal(looksLikeNeurosityDeviceId("Crown 995"), false);
  assert.equal(looksLikeNeurosityDeviceId("abc123def456ghi789jkl012mno345"), true);
});

test("picks a Crown by nickname or deviceId without requiring the 32-character id", () => {
  const devices = [
    { deviceId: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", deviceNickname: "Crown-995", status: "online" },
    { deviceId: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", deviceNickname: "Lab Crown", status: "offline" },
  ];
  assert.equal(pickCrownDevice(devices, "crown-995").deviceId, devices[0]?.deviceId);
  assert.equal(pickCrownDevice(devices, "Crown 995").deviceNickname, "Crown-995");
  assert.equal(pickCrownDevice(devices, devices[1]?.deviceId).deviceNickname, "Lab Crown");
  assert.equal(deviceMatchesWanted(devices[0]!, "995"), true);
});

test("empty wanted value selects the only claimed device", () => {
  const only = { deviceId: "cccccccccccccccccccccccccccccccc", deviceNickname: "Crown", status: "offline" };
  assert.equal(pickCrownDevice([only], "").deviceNickname, "Crown");
});

test("unknown nickname lists claimed devices instead of hanging", () => {
  assert.throws(
    () =>
      pickCrownDevice(
        [{ deviceId: "dddddddddddddddddddddddddddddddd", deviceNickname: "Office", status: "online" }],
        "crown-995",
      ),
    /did not match a claimed Crown/,
  );
});

test("Neurosity claims race is treated as a retryable auth error", () => {
  assert.equal(isTransientNeurosityAuthError("no elements in sequence"), true);
  assert.equal(isTransientNeurosityAuthError("Failed to get user claims."), true);
  assert.equal(isTransientNeurosityAuthError("wrong password"), false);
});
