import { loadCrownConfig, loadEnvLocal } from "./config.ts";
import { isAuthFailure, isMissingCredentials, runCrownHardware } from "./hardware.ts";
import { CrownMockGenerator, SAMPLE_RATE_HZ, SAMPLES_PER_CHUNK } from "./mock.ts";
import { createCrownClient, type CrownClient } from "./neurosityClient.ts";
import { createPublisher, type Publisher } from "./publisher.ts";

export type CliOptions = {
  mock: boolean;
  seed: number;
  motion: boolean;
  packetLoss: number;
  durationMs: number;
  disconnectAfterMs: number;
  fast: boolean;
  listDevices: boolean;
  endpoint?: string;
};

export function parseArgs(argv: string[]): CliOptions {
  const opts: CliOptions = {
    mock: true,
    seed: 7,
    motion: false,
    packetLoss: 0,
    durationMs: 0,
    disconnectAfterMs: 0,
    fast: false,
    listDevices: false,
  };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--mock") {
      opts.mock = true;
    } else if (arg === "--hardware") {
      opts.mock = false;
    } else if (arg === "--list-devices") {
      opts.listDevices = true;
      opts.mock = false;
    } else if (arg === "--motion") {
      opts.motion = true;
    } else if (arg === "--fast") {
      opts.fast = true;
    } else if (arg === "--seed") {
      opts.seed = Number(argv[i + 1]);
      i += 1;
    } else if (arg === "--packet-loss") {
      opts.packetLoss = Number(argv[i + 1]);
      i += 1;
    } else if (arg === "--duration-ms") {
      opts.durationMs = Number(argv[i + 1]);
      i += 1;
    } else if (arg === "--disconnect-after-ms") {
      opts.disconnectAfterMs = Number(argv[i + 1]);
      i += 1;
    } else if (arg === "--endpoint") {
      opts.endpoint = argv[i + 1];
      i += 1;
    }
  }
  return opts;
}

export async function runCrownAdapter(
  argv = process.argv.slice(2),
  publisher?: Publisher,
  client?: CrownClient,
): Promise<void> {
  const args = parseArgs(argv);
  const config = loadCrownConfig();
  loadEnvLocal();
  if (args.listDevices) {
    console.error(
      JSON.stringify({
        event: "crown_list_devices",
        service: "crown-adapter",
        msg: "Crown hardware uses the Python neurosity SDK. Run: python -m crown_adapter.main --hardware --list-devices",
      }),
    );
    return;
  }
  const pub = publisher ?? (await createPublisher(args.endpoint ?? config.endpoint));
  let stopped = false;
  const halt = () => {
    stopped = true;
  };
  process.once("SIGINT", halt);
  process.once("SIGTERM", halt);

  try {
    if (args.mock) {
      await runMockLoop(args, config, pub, () => stopped);
    } else {
      const crownClient = client ?? createCrownClient(false);
      await runCrownHardware({
        client: crownClient,
        publisher: pub,
        config,
        stopped: () => stopped,
        durationMs: args.durationMs,
      });
    }
  } finally {
    await pub.close();
  }
}

async function runMockLoop(
  args: CliOptions,
  config: ReturnType<typeof loadCrownConfig>,
  pub: Publisher,
  stopped: () => boolean,
): Promise<void> {
  const gen = new CrownMockGenerator({
    seed: args.seed,
    motion: args.motion,
    packetLoss: args.packetLoss,
    motionArtifactThreshold: config.motionArtifactThreshold,
  });
  const started = Date.now();
  let lastHeartbeat = 0;
  let simulatedMs = 0;
  let disconnectFired = false;
  const intervalMs = (SAMPLES_PER_CHUNK / SAMPLE_RATE_HZ) * 1000;

  while (!stopped()) {
    const elapsedMs = args.fast ? simulatedMs : Date.now() - started;
    if (args.disconnectAfterMs > 0 && !disconnectFired && elapsedMs >= args.disconnectAfterMs) {
      for (const event of gen.simulateDisconnect()) {
        await pub.send(event);
      }
      disconnectFired = true;
    }
    const events = gen.next();
    for (const event of events) {
      await pub.send(event);
    }
    const now = Date.now();
    if (now - lastHeartbeat >= config.heartbeatSeconds * 1000) {
      await pub.send(gen.heartbeat(pub.droppedCount()));
      lastHeartbeat = now;
    }
    if (args.fast) {
      simulatedMs += intervalMs;
      if (args.durationMs > 0 && simulatedMs >= args.durationMs) {
        break;
      }
    } else {
      if (args.durationMs > 0 && now - started >= args.durationMs) {
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }
  }

  await pub.send(gen.shutdown());
}

const entry = process.argv[1] ?? "";
if (entry.endsWith("main.ts") || entry.endsWith("main.js")) {
  runCrownAdapter().catch((error) => {
    const raw = error instanceof Error ? error.message : String(error);
    console.error(JSON.stringify({ level: "error", service: "crown-adapter", msg: safeErrorMessage(raw) }));
    process.exit(1);
  });
}

export function safeErrorMessage(raw: string): string {
  if (isMissingCredentials(raw)) {
    return "missing Neurosity credentials; copy .env.example to .env.local and set NEUROSITY_EMAIL, NEUROSITY_PASSWORD, and NEUROSITY_DEVICE_ID";
  }
  if (isAuthFailure(raw)) {
    return "Neurosity authentication failed; check .env.local (values are not logged)";
  }
  if (/no elements in sequence|failed to get user claims/i.test(raw)) {
    return "Neurosity login failed before user claims were ready; retry without passing a nickname as NEUROSITY_DEVICE_ID";
  }
  return raw;
}
