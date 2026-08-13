/** Exact integer conversion from device milliseconds to nanoseconds. */

const NS_PER_MS = 1_000_000n;

export function deviceMsToNs(deviceMs: number): number {
  if (!Number.isFinite(deviceMs)) {
    throw new Error("device time must be finite");
  }
  const ms = Math.trunc(deviceMs);
  return Number(BigInt(ms) * NS_PER_MS);
}

export function sampleIndexToDeviceMs(sampleIndex: number, sampleRateHz: number): number {
  return Math.trunc((sampleIndex * 1000) / sampleRateHz);
}

export function monotonicNs(): number {
  return Number(process.hrtime.bigint());
}
