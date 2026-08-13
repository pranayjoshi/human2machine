/**
 * Thin Neurosity SDK wrapper. Tests must use MockCrownClient and must
 * never call login() on the hardware client.
 */

export type CrownEpoch = {
  data: number[][];
  info: {
    channelNames: string[];
    samplingRate: number;
    startTime: number;
  };
};

export type CrownAccel = {
  x: number;
  y: number;
  z: number;
};

export type CrownClient = {
  login: () => Promise<void>;
  rawEpochs: () => AsyncIterable<CrownEpoch>;
  accelerometer: () => AsyncIterable<CrownAccel>;
  disconnect: () => Promise<void>;
};

export class MockCrownClient implements CrownClient {
  constructor(private readonly epochs: CrownEpoch[] = []) {}

  async login(): Promise<void> {
    return;
  }

  async *rawEpochs(): AsyncIterable<CrownEpoch> {
    for (const epoch of this.epochs) {
      yield epoch;
    }
  }

  async *accelerometer(): AsyncIterable<CrownAccel> {
    yield { x: 0, y: 0, z: 1 };
  }

  async disconnect(): Promise<void> {
    return;
  }
}

export class NeurosityCrownClient implements CrownClient {
  async login(): Promise<void> {
    const email = process.env.NEUROSITY_EMAIL;
    const password = process.env.NEUROSITY_PASSWORD;
    const deviceId = process.env.NEUROSITY_DEVICE_ID;
    if (!email || !password || !deviceId) {
      throw new Error("NEUROSITY_EMAIL, NEUROSITY_PASSWORD, and NEUROSITY_DEVICE_ID are required");
    }
    const sdk = (await import("@neurosity/sdk")) as unknown as {
      Neurosity: new (opts: { deviceId: string }) => {
        login: (creds: { email: string; password: string }) => Promise<void>;
        brainwaves: (kind: string) => unknown;
        accelerometer: () => unknown;
        disconnect?: () => Promise<void>;
      };
    };
    const client = new sdk.Neurosity({ deviceId });
    await client.login({ email, password });
    this._client = client;
  }

  async *rawEpochs(): AsyncIterable<CrownEpoch> {
    if (!this._client) {
      throw new Error("not authenticated");
    }
    yield* asAsyncIterable<CrownEpoch>(this._client.brainwaves("raw"));
  }

  async *accelerometer(): AsyncIterable<CrownAccel> {
    if (!this._client) {
      throw new Error("not authenticated");
    }
    yield* asAsyncIterable<CrownAccel>(this._client.accelerometer());
  }

  async disconnect(): Promise<void> {
    await this._client?.disconnect?.();
    this._client = undefined;
  }

  private _client?: {
    brainwaves: (kind: string) => unknown;
    accelerometer: () => unknown;
    disconnect?: () => Promise<void>;
  };
}

export function createCrownClient(mock: boolean): CrownClient {
  if (mock) {
    return new MockCrownClient();
  }
  return new NeurosityCrownClient();
}

type RxSubscriber = {
  unsubscribe?: () => void;
};

/**
 * Neurosity SDK streams are RxJS Observables. Tests may inject AsyncIterables.
 */
export async function* asAsyncIterable<T>(
  source: unknown,
  isStopped?: () => boolean,
): AsyncIterable<T> {
  if (source != null && typeof (source as AsyncIterable<T>)[Symbol.asyncIterator] === "function") {
    for await (const item of source as AsyncIterable<T>) {
      if (isStopped?.()) {
        return;
      }
      yield item;
    }
    return;
  }

  const observable = source as {
    subscribe: (...args: unknown[]) => RxSubscriber | (() => void);
  };
  if (source == null || typeof observable.subscribe !== "function") {
    throw new Error("stream is not an Observable or AsyncIterable");
  }

  const queue: T[] = [];
  let done = false;
  let failure: unknown;
  let notify: (() => void) | null = null;
  const wake = () => {
    const fn = notify;
    notify = null;
    fn?.();
  };

  const observer = {
    next(value: T) {
      queue.push(value);
      wake();
    },
    error(err: unknown) {
      failure = err;
      done = true;
      wake();
    },
    complete() {
      done = true;
      wake();
    },
  };

  let subscription: RxSubscriber | (() => void) | undefined;
  try {
    subscription = observable.subscribe(observer);
  } catch {
    subscription = observable.subscribe(observer.next, observer.error, observer.complete);
  }

  const unsubscribe = () => {
    if (typeof subscription === "function") {
      subscription();
    } else {
      subscription?.unsubscribe?.();
    }
  };

  try {
    while (!done || queue.length > 0) {
      if (isStopped?.()) {
        return;
      }
      if (queue.length === 0) {
        await Promise.race([
          new Promise<void>((resolve) => {
            notify = resolve;
          }),
          new Promise<void>((resolve) => setTimeout(resolve, 100)),
        ]);
        continue;
      }
      const item = queue.shift();
      if (item !== undefined) {
        yield item;
      }
    }
    if (failure !== undefined) {
      throw failure;
    }
  } finally {
    unsubscribe();
  }
}
