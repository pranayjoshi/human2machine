import { deviceStatusEvent, heartbeatEvent, makeEvent, type UnnormalizedEvent } from "./events.ts";
import { CROWN_CHANNELS, sanitizeSamples, scoreQuality } from "./quality.ts";
import { gaussian, mulberry32, type Rng } from "./rng.ts";
import { deviceMsToNs, sampleIndexToDeviceMs } from "./timestamps.ts";

export const SAMPLE_RATE_HZ = 256;
export const CHANNELS = 8;
export const SAMPLES_PER_CHUNK = 16;
export const MOTION_AXES = ["x", "y", "z"];

export type MockOptions = {
  seed?: number;
  motion?: boolean;
  packetLoss?: number;
  noiseStd?: number;
  alphaUv?: number;
  motionArtifactThreshold?: number;
};

export class CrownMockGenerator {
  readonly rng: Rng;
  readonly motion: boolean;
  readonly packetLoss: number;
  readonly noiseStd: number;
  readonly alphaUv: number;
  readonly motionArtifactThreshold: number;
  sampleIndex = 0;
  sequence = 0;
  packetLossCount = 0;
  chunksEmitted = 0;
  private startedMs = Date.now();
  private lastDataMs = Date.now();

  constructor(opts: MockOptions = {}) {
    this.rng = mulberry32(opts.seed ?? 7);
    this.motion = opts.motion ?? false;
    this.packetLoss = opts.packetLoss ?? 0;
    this.noiseStd = opts.noiseStd ?? 8;
    this.alphaUv = opts.alphaUv ?? 12;
    this.motionArtifactThreshold = opts.motionArtifactThreshold ?? 0.8;
  }

  next(): UnnormalizedEvent[] {
    const events: UnnormalizedEvent[] = [];
    if (this.sequence === 0) {
      events.push(deviceStatusEvent(this.sequence, "healthy", "mock stream started"));
      this.sequence += 1;
    }

    const drop = this.packetLoss > 0 && this.rng() < this.packetLoss;
    if (drop) {
      this.packetLossCount += 1;
      this.sampleIndex += SAMPLES_PER_CHUNK;
      return events;
    }

    const deviceMs = sampleIndexToDeviceMs(this.sampleIndex, SAMPLE_RATE_HZ);
    const sourceTimeNs = deviceMsToNs(deviceMs);
    const eeg = this.synthesizeEeg();
    const { samples, invalidChannels } = sanitizeSamples(eeg);
    const motion = this.synthesizeMotion();
    const quality = scoreQuality({
      samples,
      packetLossCount: this.packetLossCount,
      chunksSinceLoss: this.chunksEmitted,
      motionMagnitude: motion.magnitude,
      motionArtifactThreshold: this.motionArtifactThreshold,
    });
    if (invalidChannels.length > 0) {
      quality.flags.push("sanitized_non_finite");
    }

    events.push(
      makeEvent({
        eventType: "biosignal.chunk",
        modality: "eeg",
        sequence: this.sequence,
        sourceTimeNs,
        quality: quality.score,
        payload: {
          sample_rate_hz: SAMPLE_RATE_HZ,
          channel_names: [...CROWN_CHANNELS],
          sample_count: SAMPLES_PER_CHUNK,
          samples,
          units: "microvolts",
          filters_applied: ["crown_raw_filtered"],
          packet_loss_count: this.packetLossCount,
          clock_confidence: 1,
          estimated_first_sample_ns: sourceTimeNs,
        },
      }),
    );
    this.sequence += 1;

    events.push(
      makeEvent({
        eventType: "motion.chunk",
        modality: "imu",
        sequence: this.sequence,
        sourceTimeNs,
        quality: quality.score,
        payload: {
          sample_rate_hz: SAMPLE_RATE_HZ / SAMPLES_PER_CHUNK,
          axes: MOTION_AXES,
          sample_count: 1,
          samples: motion.samples,
          units: "g",
          magnitude: motion.magnitude,
        },
      }),
    );
    this.sequence += 1;

    events.push(
      makeEvent({
        eventType: "data.quality",
        modality: "eeg",
        sequence: this.sequence,
        sourceTimeNs,
        quality: quality.score,
        payload: {
          score: quality.score,
          components: {
            packet_quality: quality.packet_quality,
            channel_validity: quality.channel_validity,
            motion_penalty: quality.motion_penalty,
          },
          flags: quality.flags,
        },
      }),
    );
    this.sequence += 1;

    if (this.chunksEmitted > 0 && this.chunksEmitted % 16 === 0) {
      events.push(this.shadowFeature(sourceTimeNs, quality.score, motion.magnitude));
    }

    this.sampleIndex += SAMPLES_PER_CHUNK;
    this.chunksEmitted += 1;
    this.lastDataMs = Date.now();
    return events;
  }

  heartbeat(dropped: number): UnnormalizedEvent {
    const event = heartbeatEvent(
      this.sequence,
      (Date.now() - this.startedMs) / 1000,
      Date.now() - this.lastDataMs,
      dropped,
      dropped > 0 ? "degraded" : "healthy",
    );
    this.sequence += 1;
    return event;
  }

  shutdown(): UnnormalizedEvent {
    const event = deviceStatusEvent(this.sequence, "offline", "adapter stopping");
    this.sequence += 1;
    return event;
  }

  private shadowFeature(sourceTimeNs: number, quality: number, magnitude: number): UnnormalizedEvent {
    const artifact = magnitude > this.motionArtifactThreshold;
    const event = makeEvent({
      eventType: "modality.feature",
      modality: "eeg",
      sequence: this.sequence,
      sourceTimeNs,
      quality,
      payload: {
        feature_name: "eeg_shadow",
        window_start_ns: sourceTimeNs,
        window_end_ns: sourceTimeNs + deviceMsToNs(62),
        label: artifact ? "artifact" : "ok",
        confidence: quality,
        candidate_scores: {
          ok: artifact ? Math.max(0, 1 - quality) : quality,
          artifact: artifact ? quality : Math.max(0, 1 - quality),
        },
        model_id: "crown-shadow-v0",
        shadow_only: true,
      },
    });
    this.sequence += 1;
    return event;
  }

  private synthesizeEeg(): number[][] {
    const samples: number[][] = Array.from({ length: CHANNELS }, () => Array<number>(SAMPLES_PER_CHUNK).fill(0));
    for (let n = 0; n < SAMPLES_PER_CHUNK; n += 1) {
      const t = (this.sampleIndex + n) / SAMPLE_RATE_HZ;
      const alpha = Math.sin(2 * Math.PI * 10 * t) * this.alphaUv;
      const motionBleed = this.motion ? Math.sin(2 * Math.PI * 1.2 * t) * 40 + gaussian(this.rng) * 15 : 0;
      for (let ch = 0; ch < CHANNELS; ch += 1) {
        const posterior = ch === 3 || ch === 4 ? alpha : alpha * 0.25;
        samples[ch][n] = posterior + gaussian(this.rng) * this.noiseStd + motionBleed;
      }
    }
    return samples;
  }

  private synthesizeMotion(): { samples: number[][]; magnitude: number } {
    const base = this.motion ? 1.4 + Math.abs(gaussian(this.rng)) * 0.6 : 0.05;
    const x = this.motion ? base * (0.4 + this.rng()) : gaussian(this.rng) * 0.02;
    const y = this.motion ? base * (0.3 + this.rng()) : gaussian(this.rng) * 0.02;
    const z = this.motion ? 1 + gaussian(this.rng) * 0.2 : 1 + gaussian(this.rng) * 0.01;
    const magnitude = Math.sqrt(x * x + y * y + z * z);
    return { samples: [[x], [y], [z]], magnitude };
  }
}
