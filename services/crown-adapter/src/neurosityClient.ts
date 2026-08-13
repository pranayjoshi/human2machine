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
    const stream = this._client.brainwaves("raw");
    for await (const epoch of stream as AsyncIterable<CrownEpoch>) {
      yield epoch;
    }
  }

  async *accelerometer(): AsyncIterable<CrownAccel> {
    if (!this._client) {
      throw new Error("not authenticated");
    }
    const stream = this._client.accelerometer();
    for await (const sample of stream as AsyncIterable<CrownAccel>) {
      yield sample;
    }
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
