import { loadCrownConfig, loadEnvLocal } from "./config.ts";
import { runCrownHardware } from "./hardware.ts";
import { CrownMockGenerator } from "./mock.ts";
import { createCrownClient, type CrownClient } from "./neurosityClient.ts";
import { createPublisher, type Publisher } from "./publisher.ts";

export type CliOptions = {
  mock: boolean;
  seed: number;
  motion: boolean;
  packetLoss: number;
  durationMs: number;
  endpoint?: string;
};

export function parseArgs(argv: string[]): CliOptions {
  const opts: CliOptions = {
    mock: true,
    seed: 7,
    motion: false,
    packetLoss: 0,
    durationMs: 0,
  };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--mock") {
      opts.mock = true;
    } else if (arg === "--hardware") {
      opts.mock = false;
    } else if (arg === "--motion") {
      opts.motion = true;
    } else if (arg === "--seed") {
      opts.seed = Number(argv[i + 1]);
      i += 1;
    } else if (arg === "--packet-loss") {
      opts.packetLoss = Number(argv[i + 1]);
      i += 1;
    } else if (arg === "--duration-ms") {
      opts.durationMs = Number(argv[i + 1]);
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
  const intervalMs = (16 / 256) * 1000;

  while (!stopped()) {
    const events = gen.next();
    for (const event of events) {
      await pub.send(event);
    }
    const now = Date.now();
    if (now - lastHeartbeat >= config.heartbeatSeconds * 1000) {
      await pub.send(gen.heartbeat(pub.droppedCount()));
      lastHeartbeat = now;
    }
    if (args.durationMs > 0 && now - started >= args.durationMs) {
      break;
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }

  await pub.send(gen.shutdown());
}

const entry = process.argv[1] ?? "";
if (entry.endsWith("main.ts") || entry.endsWith("main.js")) {
  runCrownAdapter().catch((error) => {
    const raw = error instanceof Error ? error.message : String(error);
    const msg = /password|passwd|token|secret|authorization/i.test(raw)
      ? "authentication failed"
      : raw;
    console.error(JSON.stringify({ level: "error", msg }));
    process.exit(1);
  });
}
