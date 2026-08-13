export const CROWN_CHANNELS = ["CP3", "C3", "F5", "PO3", "PO4", "F6", "C4", "CP4"] as const;

export type QualityInput = {
  samples: number[][];
  packetLossCount: number;
  chunksSinceLoss: number;
  motionMagnitude: number;
  motionArtifactThreshold: number;
};

export type QualityResult = {
  score: number;
  packet_quality: number;
  channel_validity: number;
  motion_penalty: number;
  flags: string[];
  invalid_channels: string[];
};

function clamp01(value: number): number {
  if (!Number.isFinite(value)) {
    return 0;
  }
  return Math.min(1, Math.max(0, value));
}

export function channelHasNonFinite(channel: number[]): boolean {
  return channel.some((value) => !Number.isFinite(value));
}

export function channelIsFlat(channel: number[], epsilon = 1e-9): boolean {
  if (channel.length < 2) {
    return true;
  }
  const min = Math.min(...channel);
  const max = Math.max(...channel);
  return max - min <= epsilon;
}

export function clipRatio(channel: number[], clipAbs = 200): number {
  if (channel.length === 0) {
    return 0;
  }
  let clipped = 0;
  for (const value of channel) {
    if (Math.abs(value) >= clipAbs) {
      clipped += 1;
    }
  }
  return clipped / channel.length;
}

export function sanitizeSamples(samples: number[][]): {
  samples: number[][];
  invalidChannels: number[];
} {
  const invalidChannels: number[] = [];
  const cleaned = samples.map((channel, index) => {
    let invalid = false;
    const next = channel.map((value) => {
      if (!Number.isFinite(value)) {
        invalid = true;
        return 0;
      }
      return value;
    });
    if (invalid) {
      invalidChannels.push(index);
    }
    return next;
  });
  return { samples: cleaned, invalidChannels };
}

export function scoreQuality(input: QualityInput): QualityResult {
  const flags: string[] = [];
  const invalidNames: string[] = [];
  const channelCount = input.samples.length || 1;
  let validChannels = 0;

  for (let i = 0; i < input.samples.length; i += 1) {
    const channel = input.samples[i];
    const name = CROWN_CHANNELS[i] ?? `ch${i}`;
    if (channelHasNonFinite(channel)) {
      invalidNames.push(name);
      flags.push(`non_finite:${name}`);
      continue;
    }
    if (channelIsFlat(channel)) {
      flags.push(`flat:${name}`);
      continue;
    }
    if (clipRatio(channel) > 0.05) {
      flags.push(`clipping:${name}`);
    }
    validChannels += 1;
  }

  const channel_validity = clamp01(validChannels / channelCount);
  const lossRatio =
    input.packetLossCount <= 0
      ? 0
      : input.packetLossCount / (input.packetLossCount + Math.max(1, input.chunksSinceLoss));
  const packet_quality = clamp01(1 - Math.min(1, lossRatio * 4 + (input.packetLossCount > 0 && input.chunksSinceLoss === 0 ? 0.2 : 0)));

  const over = Math.max(0, input.motionMagnitude - input.motionArtifactThreshold);
  const motion_penalty = clamp01(1 / (1 + 2.5 * over));
  if (over > 0) {
    flags.push("motion_artifact");
  }
  if (input.packetLossCount > 0) {
    flags.push("packet_loss");
  }

  const score = clamp01(packet_quality * channel_validity * motion_penalty);
  return {
    score,
    packet_quality,
    channel_validity,
    motion_penalty,
    flags,
    invalid_channels: invalidNames,
  };
}
