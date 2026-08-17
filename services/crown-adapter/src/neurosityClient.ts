/**
 * Test doubles and helpers for the (legacy) TypeScript Crown path.
 * Live Crown hardware uses the Python neurosity SDK in crown_adapter/.
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

export type CrownDeviceInfo = {
  deviceId?: string;
  deviceNickname?: string;
  status?: string;
};

export function normalizeCrownName(value: string): string {
  return value.trim().toLowerCase().replace(/[\s_]+/g, "-");
}

export function looksLikeNeurosityDeviceId(value: string): boolean {
  const trimmed = value.trim();
  if (trimmed.length < 20) {
    return false;
  }
  if (/^crown[-_]?\d+$/i.test(trimmed)) {
    return false;
  }
  return /^[A-Za-z0-9]+$/.test(trimmed);
}

export function deviceMatchesWanted(device: CrownDeviceInfo, wanted: string): boolean {
  const needle = wanted.trim();
  if (!needle) {
    return false;
  }
  const id = device.deviceId ?? "";
  const nick = device.deviceNickname ?? "";
  if (id && id === needle) {
    return true;
  }
  if (nick && nick.toLowerCase() === needle.toLowerCase()) {
    return true;
  }
  const left = normalizeCrownName(nick);
  const right = normalizeCrownName(needle);
  if (left && left === right) {
    return true;
  }
  if (left.replace(/^crown-/, "") === right.replace(/^crown-/, "") && left.replace(/^crown-/, "") !== "") {
    return true;
  }
  return false;
}

export function summarizeCrownDevices(devices: CrownDeviceInfo[]): string {
  if (devices.length === 0) {
    return "none";
  }
  return devices
    .map((device) => {
      const nick = device.deviceNickname || "unnamed";
      const status = device.status || "unknown";
      return `${nick} (${status})`;
    })
    .join(", ");
}

export function pickCrownDevice(devices: CrownDeviceInfo[], wanted?: string): CrownDeviceInfo {
  if (devices.length === 0) {
    throw new Error("no Crown devices claimed on this Neurosity account");
  }
  const needle = (wanted ?? "").trim();
  if (needle) {
    const match = devices.find((device) => deviceMatchesWanted(device, needle));
    if (!match) {
      throw new Error(
        `NEUROSITY_DEVICE_ID did not match a claimed Crown (${summarizeCrownDevices(devices)}). Use the nickname or the 32-character Device ID from the Neurosity app Settings → Device Info.`,
      );
    }
    return match;
  }
  const online = devices.filter((device) => (device.status ?? "").toLowerCase() === "online");
  if (online.length === 1) {
    return online[0];
  }
  if (devices.length === 1) {
    return devices[0];
  }
  throw new Error(
    `multiple Crown devices on this account; set NEUROSITY_DEVICE_ID to a nickname or deviceId (${summarizeCrownDevices(devices)})`,
  );
}

export function createCrownClient(mock: boolean): CrownClient {
  if (mock) {
    return new MockCrownClient();
  }
  throw new Error(
    "Crown hardware uses the Python neurosity SDK; run python -m crown_adapter.main --hardware",
  );
}

export function isTransientNeurosityAuthError(message: string): boolean {
  return /no elements in sequence|failed to get user claims/i.test(message);
}
