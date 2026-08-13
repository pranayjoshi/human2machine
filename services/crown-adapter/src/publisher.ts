import { createConnection, type Socket } from "node:net";

import type { UnnormalizedEvent } from "./events.ts";

export type Publisher = {
  send: (event: UnnormalizedEvent) => Promise<boolean>;
  close: () => Promise<void>;
  droppedCount: () => number;
};

type ZmqPush = {
  connect: (endpoint: string) => void;
  send: (payload: Buffer | string) => Promise<void>;
  close: () => Promise<void>;
};

/**
 * Native zeromq is preferred (ZMQ PUSH to tcp://127.0.0.1:5555).
 * If the zeromq native addon fails to load, fall back to net.Socket
 * writing one JSON object as a single TCP write. This fallback is NOT
 * ZMQ-framed; it still emits valid contract JSON when the addon cannot
 * be built.
 */
export async function createPublisher(
  endpoint = "tcp://127.0.0.1:5555",
  highWaterMark = 256,
): Promise<Publisher> {
  try {
    const zmq = await import("zeromq");
    const sock = new zmq.Push({ linger: 0, sendHighWaterMark: highWaterMark }) as unknown as ZmqPush;
    sock.connect(endpoint);
    return boundZmqPublisher(sock, highWaterMark);
  } catch {
    return tcpFallbackPublisher(endpoint, highWaterMark);
  }
}

function boundZmqPublisher(sock: ZmqPush, highWaterMark: number): Publisher {
  let dropped = 0;
  let queued = 0;
  return {
    async send(event: UnnormalizedEvent) {
      if (queued >= highWaterMark) {
        dropped += 1;
        return false;
      }
      queued += 1;
      try {
        await sock.send(JSON.stringify(event));
        queued -= 1;
        return true;
      } catch {
        queued -= 1;
        dropped += 1;
        return false;
      }
    },
    async close() {
      await sock.close();
    },
    droppedCount: () => dropped,
  };
}

function parseTcpEndpoint(endpoint: string): { host: string; port: number } {
  const url = new URL(endpoint.replace(/^tcp:/, "http:"));
  return { host: url.hostname, port: Number(url.port) };
}

function tcpFallbackPublisher(endpoint: string, highWaterMark: number): Publisher {
  const { host, port } = parseTcpEndpoint(endpoint);
  let socket: Socket | null = null;
  let dropped = 0;
  let connecting = false;
  const queue: string[] = [];

  const flush = () => {
    if (!socket || socket.destroyed) {
      return;
    }
    while (queue.length > 0) {
      const frame = queue.shift();
      if (frame === undefined) {
        break;
      }
      socket.write(`${frame}\n`);
    }
  };

  const ensure = () => {
    if (socket || connecting) {
      return;
    }
    connecting = true;
    const conn = createConnection({ host, port });
    conn.setNoDelay(true);
    conn.on("connect", () => {
      socket = conn;
      connecting = false;
      flush();
    });
    conn.on("error", () => {
      connecting = false;
      socket = null;
      dropped += queue.length;
      queue.length = 0;
    });
    conn.on("close", () => {
      socket = null;
      connecting = false;
    });
  };

  return {
    async send(event: UnnormalizedEvent) {
      if (queue.length >= highWaterMark) {
        dropped += 1;
        return false;
      }
      queue.push(JSON.stringify(event));
      ensure();
      if (!socket) {
        return true;
      }
      flush();
      return true;
    },
    async close() {
      queue.length = 0;
      socket?.destroy();
      socket = null;
    },
    droppedCount: () => dropped,
  };
}

export function memoryPublisher(): Publisher & { events: UnnormalizedEvent[] } {
  const events: UnnormalizedEvent[] = [];
  return {
    events,
    async send(event: UnnormalizedEvent) {
      events.push(event);
      return true;
    },
    async close() {
      return;
    },
    droppedCount: () => 0,
  };
}
