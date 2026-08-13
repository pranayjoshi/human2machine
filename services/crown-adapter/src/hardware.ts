import type { CrownConfig } from "./config.ts";
import { deviceStatusEvent, heartbeatEvent, makeEvent, type UnnormalizedEvent } from "./events.ts";
import type { CrownAccel, CrownClient, CrownEpoch } from "./neurosityClient.ts";
import type { Publisher } from "./publisher.ts";
import { CROWN_CHANNELS, sanitizeSamples, scoreQuality } from "./quality.ts";
import { deviceMsToNs } from "./timestamps.ts";

const MOTION_AXES = ["x", "y", "z"];
const DEVICE_ALIAS = "crown";

export type HardwareDeps = {
  client: CrownClient;
  publisher: Publisher;
  config: CrownConfig;
  stopped: () => boolean;
  durationMs: number;
  now?: () => number;
  sleep?: (ms: number) => Promise<void>;
};

type AccelState = {
  x: number;
  y: number;
  z: number;
  magnitude: number;
  hasSample: boolean;
};

export async function runCrownHardware(deps: HardwareDeps): Promise<void> {
  const now = deps.now ?? Date.now;
  const sleep = deps.sleep ?? defaultSleep;
  const started = now();
  const deadline = deps.durationMs > 0 ? started + deps.durationMs : 0;
  let sequence = 0;
  let chunksEmitted = 0;
  let packetLossCount = 0;
  let lastStartTime = Number.NEGATIVE_INFINITY;
  let lastDataMs = now();
  let lastHeartbeat = 0;
  let attempt = 0;
  let clockOffsetNs: number | null = null;
  const accel: AccelState = { x: 0, y: 0, z: 0, magnitude: 0, hasSample: false };

  const nextSeq = () => {
    const value = sequence;
    sequence += 1;
    return value;
  };

  const send = async (event: UnnormalizedEvent) => {
    await deps.publisher.send(event);
  };

  const maybeHeartbeat = async (status: string) => {
    const t = now();
    if (t - lastHeartbeat < deps.config.heartbeatSeconds * 1000) {
      return;
    }
    const age = t - lastDataMs;
    await send(
      heartbeatEvent(
        nextSeq(),
        (t - started) / 1000,
        Number.isFinite(age) ? age : null,
        deps.publisher.droppedCount(),
        status,
      ),
    );
    lastHeartbeat = t;
  };

  const timedOut = () => deadline > 0 && now() >= deadline;
  const halt = () => deps.stopped() || timedOut();

  try {
    while (!halt()) {
      try {
        await deps.client.login();
        attempt = 0;
        await send(deviceStatusEvent(nextSeq(), "healthy", "crown stream started", {}, DEVICE_ALIAS));
        await consumeLiveStreams({
          client: deps.client,
          config: deps.config,
          accel,
          halt,
          send,
          nextSeq,
          maybeHeartbeat,
          onEpoch: async (epoch) => {
            const startTime = epoch.info?.startTime;
            if (typeof startTime === "number" && Number.isFinite(startTime) && startTime <= lastStartTime) {
              return;
            }
            if (typeof startTime === "number" && Number.isFinite(startTime)) {
              lastStartTime = startTime;
            }
            const events = convertEpoch(epoch, accel, {
              sequence: nextSeq,
              packetLossCount,
              chunksEmitted,
              motionArtifactThreshold: deps.config.motionArtifactThreshold,
              expectedChannels: deps.config.channels,
              expectedSamples: deps.config.samplesPerChunk,
              sampleRateHz: deps.config.sampleRateHz,
              shadowOnly: deps.config.shadowOnly,
              clockOffsetNs,
            });
            if (events.rejected) {
              packetLossCount += 1;
              return;
            }
            if (events.clockOffsetNs !== null) {
              clockOffsetNs = events.clockOffsetNs;
            }
            for (const event of events.events) {
              await send(event);
            }
            chunksEmitted += 1;
            lastDataMs = now();
          },
        });
        if (halt()) {
          break;
        }
        await send(
          deviceStatusEvent(nextSeq(), "degraded", "crown stream ended; reconnecting", {}, DEVICE_ALIAS),
        );
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        if (isMissingCredentials(message)) {
          await send(deviceStatusEvent(nextSeq(), "offline", "missing Neurosity credentials", {}, DEVICE_ALIAS));
          throw error;
        }
        await send(
          deviceStatusEvent(
            nextSeq(),
            "degraded",
            "crown disconnected; reconnecting",
            { reconnect_attempt: attempt + 1 },
            DEVICE_ALIAS,
          ),
        );
      }

      if (halt()) {
        break;
      }
      const waitMs = backoffMs(attempt, deps.config.reconnectMaxSeconds);
      attempt += 1;
      clockOffsetNs = null;
      try {
        await deps.client.disconnect();
      } catch {
        // ignore disconnect errors during backoff
      }
      const waitEnd = now() + waitMs;
      while (!halt() && now() < waitEnd) {
        await maybeHeartbeat("degraded");
        await sleep(Math.min(100, waitEnd - now()));
      }
    }
  } finally {
    await send(deviceStatusEvent(nextSeq(), "offline", "adapter stopping", {}, DEVICE_ALIAS));
    try {
      await deps.client.disconnect();
    } catch {
      // ignore
    }
  }
}

export function backoffMs(attempt: number, capSeconds: number): number {
  const capMs = Math.max(1000, capSeconds * 1000);
  return Math.min(capMs, 1000 * 2 ** Math.max(0, attempt));
}

export function isMissingCredentials(message: string): boolean {
  return (
    message.includes("NEUROSITY_EMAIL") ||
    message.includes("NEUROSITY_PASSWORD") ||
    message.includes("NEUROSITY_DEVICE_ID")
  );
}

export function convertEpoch(
  epoch: CrownEpoch,
  accel: AccelState,
  opts: {
    sequence: () => number;
    packetLossCount: number;
    chunksEmitted: number;
    motionArtifactThreshold: number;
    expectedChannels: number;
    expectedSamples: number;
    sampleRateHz: number;
    shadowOnly: boolean;
    clockOffsetNs: number | null;
  },
): { events: UnnormalizedEvent[]; rejected: boolean; clockOffsetNs: number | null } {
  const samples = toChannelMajor(epoch.data, opts.expectedChannels);
  const channelNames =
    epoch.info?.channelNames?.length === opts.expectedChannels
      ? epoch.info.channelNames
      : [...CROWN_CHANNELS];
  const sampleCount = samples[0]?.length ?? 0;
  if (samples.length !== opts.expectedChannels || sampleCount === 0) {
    return { events: [], rejected: true, clockOffsetNs: opts.clockOffsetNs };
  }

  const { samples: cleaned, invalidChannels } = sanitizeSamples(samples);
  const startMs = epoch.info?.startTime;
  let sourceTimeNs: number | null = null;
  let clockOffsetNs = opts.clockOffsetNs;
  if (typeof startMs === "number" && Number.isFinite(startMs)) {
    sourceTimeNs = deviceMsToNs(startMs);
    if (clockOffsetNs === null) {
      clockOffsetNs = Date.now() * 1_000_000 - sourceTimeNs;
    }
  }

  const motionMagnitude = accel.hasSample ? accel.magnitude : 0;
  const quality = scoreQuality({
    samples: cleaned,
    packetLossCount: opts.packetLossCount,
    chunksSinceLoss: opts.chunksEmitted,
    motionMagnitude,
    motionArtifactThreshold: opts.motionArtifactThreshold,
  });
  if (invalidChannels.length > 0) {
    quality.flags.push("sanitized_non_finite");
  }
  if (sampleCount !== opts.expectedSamples) {
    quality.flags.push("unexpected_epoch_length");
  }

  const sampleRate = epoch.info?.samplingRate || opts.sampleRateHz;
  const events: UnnormalizedEvent[] = [];
  events.push(
    makeEvent({
      eventType: "biosignal.chunk",
      modality: "eeg",
      sequence: opts.sequence(),
      sourceTimeNs,
      quality: quality.score,
      payload: {
        sample_rate_hz: sampleRate,
        channel_names: channelNames,
        sample_count: sampleCount,
        samples: cleaned,
        units: "microvolts",
        filters_applied: ["crown_raw_filtered"],
        packet_loss_count: opts.packetLossCount,
        clock_confidence: sourceTimeNs === null ? 0.2 : 1,
        estimated_first_sample_ns: sourceTimeNs,
      },
    }),
  );

  if (accel.hasSample) {
    events.push(
      makeEvent({
        eventType: "motion.chunk",
        modality: "imu",
        sequence: opts.sequence(),
        sourceTimeNs,
        quality: quality.score,
        payload: {
          sample_rate_hz: sampleRate / Math.max(sampleCount, 1),
          axes: MOTION_AXES,
          sample_count: 1,
          samples: [[accel.x], [accel.y], [accel.z]],
          units: "g",
          magnitude: accel.magnitude,
        },
      }),
    );
  }

  events.push(
    makeEvent({
      eventType: "data.quality",
      modality: "eeg",
      sequence: opts.sequence(),
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

  if (opts.chunksEmitted > 0 && opts.chunksEmitted % 16 === 0 && sourceTimeNs !== null) {
    const artifact = motionMagnitude > opts.motionArtifactThreshold;
    events.push(
      makeEvent({
        eventType: "modality.feature",
        modality: "eeg",
        sequence: opts.sequence(),
        sourceTimeNs,
        quality: quality.score,
        payload: {
          feature_name: "eeg_shadow",
          window_start_ns: sourceTimeNs,
          window_end_ns: sourceTimeNs + deviceMsToNs(62),
          label: artifact ? "artifact" : "ok",
          confidence: quality.score,
          candidate_scores: {
            ok: artifact ? Math.max(0, 1 - quality.score) : quality.score,
            artifact: artifact ? quality.score : Math.max(0, 1 - quality.score),
          },
          model_id: "crown-shadow-v0",
          shadow_only: opts.shadowOnly,
        },
      }),
    );
  }

  return { events, rejected: false, clockOffsetNs };
}

export function toChannelMajor(data: number[][], expectedChannels: number): number[][] {
  if (!Array.isArray(data) || data.length === 0) {
    return [];
  }
  if (data.length === expectedChannels) {
    return data;
  }
  if (data[0]?.length === expectedChannels) {
    return Array.from({ length: expectedChannels }, (_, ch) => data.map((row) => Number(row[ch])));
  }
  return data;
}

function updateAccel(target: AccelState, sample: CrownAccel): void {
  const x = Number(sample.x);
  const y = Number(sample.y);
  const z = Number(sample.z);
  target.x = x;
  target.y = y;
  target.z = z;
  target.magnitude = Math.sqrt(x * x + y * y + z * z);
  target.hasSample = Number.isFinite(target.magnitude);
}

async function consumeLiveStreams(opts: {
  client: CrownClient;
  config: CrownConfig;
  accel: AccelState;
  halt: () => boolean;
  send: (event: UnnormalizedEvent) => Promise<void>;
  nextSeq: () => number;
  maybeHeartbeat: (status: string) => Promise<void>;
  onEpoch: (epoch: CrownEpoch) => Promise<void>;
}): Promise<void> {
  let active = true;
  const accelTask = drainIterable(opts.client.accelerometer(), opts.halt, () => active, (sample) => {
    updateAccel(opts.accel, normalizeAccel(sample));
  });
  const eegTask = drainIterable(opts.client.rawEpochs(), opts.halt, () => active, async (epoch) => {
    await opts.onEpoch(normalizeEpoch(epoch));
    await opts.maybeHeartbeat("healthy");
  });
  const heartbeatTask = (async () => {
    while (active && !opts.halt()) {
      await opts.maybeHeartbeat("healthy");
      await defaultSleep(200);
    }
  })();
  try {
    await Promise.all([accelTask, eegTask]);
  } finally {
    active = false;
    await heartbeatTask;
  }
}

async function drainIterable<T>(
  source: AsyncIterable<T>,
  halt: () => boolean,
  active: () => boolean,
  onItem: (item: T) => void | Promise<void>,
): Promise<void> {
  const iterator = source[Symbol.asyncIterator]();
  try {
    while (active() && !halt()) {
      const next = iterator.next();
      const result = await Promise.race([
        next,
        pollHalt(halt, active).then(() => ({ done: true as const, value: undefined })),
      ]);
      if (result.done) {
        return;
      }
      await onItem(result.value as T);
    }
  } finally {
    await iterator.return?.();
  }
}

async function pollHalt(halt: () => boolean, active: () => boolean): Promise<void> {
  while (active() && !halt()) {
    await defaultSleep(50);
  }
}

function normalizeEpoch(epoch: CrownEpoch): CrownEpoch {
  const record = epoch as CrownEpoch & { info?: CrownEpoch["info"]; data?: number[][] };
  return {
    data: record.data ?? [],
    info: {
      channelNames: record.info?.channelNames ?? [...CROWN_CHANNELS],
      samplingRate: record.info?.samplingRate ?? 256,
      startTime: record.info?.startTime ?? 0,
    },
  };
}

function normalizeAccel(sample: CrownAccel): CrownAccel {
  const record = sample as CrownAccel & { acceleration?: CrownAccel };
  if (record.acceleration) {
    return {
      x: record.acceleration.x,
      y: record.acceleration.y,
      z: record.acceleration.z,
    };
  }
  return { x: sample.x, y: sample.y, z: sample.z };
}

function defaultSleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, Math.max(0, ms)));
}
