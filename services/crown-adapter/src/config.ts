import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import yaml from "js-yaml";

export type CrownConfig = {
  sampleRateHz: number;
  channels: number;
  samplesPerChunk: number;
  heartbeatSeconds: number;
  motionArtifactThreshold: number;
  shadowOnly: boolean;
  reconnectMaxSeconds: number;
  endpoint: string;
};

const DEFAULTS: CrownConfig = {
  sampleRateHz: 256,
  channels: 8,
  samplesPerChunk: 16,
  heartbeatSeconds: 2,
  motionArtifactThreshold: 0.8,
  shadowOnly: true,
  reconnectMaxSeconds: 30,
  endpoint: "tcp://127.0.0.1:5555",
};

export function findRepoRoot(start = dirname(fileURLToPath(import.meta.url))): string {
  let dir = start;
  for (let i = 0; i < 8; i += 1) {
    if (existsSync(join(dir, "configs", "local.yaml"))) {
      return dir;
    }
    dir = dirname(dir);
  }
  return process.cwd();
}

export function loadCrownConfig(repoRoot = findRepoRoot()): CrownConfig {
  const config: CrownConfig = { ...DEFAULTS };
  try {
    const local = yaml.load(readFileSync(join(repoRoot, "configs", "local.yaml"), "utf8")) as {
      runtime?: { ports?: { adapter_push?: string } };
    };
    if (local?.runtime?.ports?.adapter_push) {
      config.endpoint = local.runtime.ports.adapter_push;
    }
  } catch {
    // defaults
  }
  try {
    const modalities = yaml.load(readFileSync(join(repoRoot, "configs", "modalities.yaml"), "utf8")) as {
      crown?: {
        sample_rate_hz?: number;
        channels?: number;
        samples_per_chunk?: number;
        heartbeat_seconds?: number;
        motion_artifact_threshold?: number;
        shadow_only?: boolean;
        reconnect_max_seconds?: number;
      };
    };
    const crown = modalities?.crown;
    if (crown?.sample_rate_hz) config.sampleRateHz = crown.sample_rate_hz;
    if (crown?.channels) config.channels = crown.channels;
    if (crown?.samples_per_chunk) config.samplesPerChunk = crown.samples_per_chunk;
    if (crown?.heartbeat_seconds) config.heartbeatSeconds = crown.heartbeat_seconds;
    if (crown?.motion_artifact_threshold) config.motionArtifactThreshold = crown.motion_artifact_threshold;
    if (crown?.shadow_only !== undefined) config.shadowOnly = crown.shadow_only;
    if (crown?.reconnect_max_seconds) config.reconnectMaxSeconds = crown.reconnect_max_seconds;
  } catch {
    // defaults
  }
  return config;
}

/**
 * Load `.env.local` into process.env without logging values or keys.
 * Existing non-empty environment variables win.
 */
export function loadEnvLocal(repoRoot = findRepoRoot(), env: NodeJS.ProcessEnv = process.env): boolean {
  const envPath = join(repoRoot, ".env.local");
  if (!existsSync(envPath)) {
    return false;
  }
  applyEnvFile(readFileSync(envPath, "utf8"), env);
  return true;
}

export function applyEnvFile(contents: string, env: NodeJS.ProcessEnv = process.env): void {
  for (const rawLine of contents.split(/\r?\n/)) {
    let line = rawLine.trim();
    if (!line || line.startsWith("#")) {
      continue;
    }
    if (line.startsWith("export ")) {
      line = line.slice(7).trim();
    }
    const eq = line.indexOf("=");
    if (eq <= 0) {
      continue;
    }
    const key = line.slice(0, eq).trim();
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(key)) {
      continue;
    }
    const current = env[key];
    if (current !== undefined && current !== "") {
      continue;
    }
    let value = line.slice(eq + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    env[key] = value;
  }
}
