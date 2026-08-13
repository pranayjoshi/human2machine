"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { api, liveSocketUrl } from "./api";
import type { LiveState, PlotSnapshot, PublicConfig } from "./types";
import { PLOT_CAP } from "./types";

type PlotBuffers = {
  eeg: PlotSnapshot;
  emg: PlotSnapshot;
};

type LiveContextValue = {
  snapshot: LiveState | null;
  config: PublicConfig | null;
  connected: boolean;
  plots: PlotBuffers;
  error: string | null;
};

const LiveContext = createContext<LiveContextValue | null>(null);

const emptyPlot = (names: string[]): PlotSnapshot => ({
  channel_names: names,
  samples: Object.fromEntries(names.map((name) => [name, []])),
  t_ms: [],
});

function mergePlot(current: PlotSnapshot, incoming: PlotSnapshot): PlotSnapshot {
  const names = incoming.channel_names.length ? incoming.channel_names : current.channel_names;
  const samples: Record<string, number[]> = {};
  for (const name of names) {
    const prev = current.samples[name] ?? [];
    const next = incoming.samples[name] ?? [];
    const added = next.length <= 4 ? next.slice(-1) : next.slice(-2);
    samples[name] = [...prev, ...added].slice(-PLOT_CAP);
  }
  const tPrev = current.t_ms;
  const tNext = incoming.t_ms.slice(-1);
  return { channel_names: names, samples, t_ms: [...tPrev, ...tNext].slice(-PLOT_CAP) };
}

export function LiveProvider({ children }: { children: ReactNode }) {
  const [snapshot, setSnapshot] = useState<LiveState | null>(null);
  const [config, setConfig] = useState<PublicConfig | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [plots, setPlots] = useState<PlotBuffers>({
    eeg: emptyPlot(["C3", "C4", "Cz", "F3", "F4", "P3", "P4", "Oz"]),
    emg: emptyPlot(["emg_flexor", "emg_extensor", "emg_pronator", "emg_aux"]),
  });
  const retryRef = useRef<number | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    api.config().then(setConfig).catch((err: Error) => setError(err.message));
  }, []);

  useEffect(() => {
    let cancelled = false;

    const connect = () => {
      if (cancelled) return;
      const ws = new WebSocket(liveSocketUrl());
      wsRef.current = ws;
      ws.onopen = () => {
        setConnected(true);
        setError(null);
        ws.send(JSON.stringify({ type: "snapshot" }));
      };
      ws.onmessage = (event) => {
        const message = JSON.parse(event.data) as {
          type: string;
          payload: LiveState | { stream?: string; channel_names?: string[]; samples?: Record<string, number[]>; t_ms?: number[] };
        };
        if (message.type === "snapshot") {
          const state = message.payload as LiveState;
          setSnapshot(state);
          setPlots({
            eeg: {
              channel_names: state.eeg.channel_names,
              samples: Object.fromEntries(
                state.eeg.channel_names.map((name) => [name, (state.eeg.samples[name] ?? []).slice(-PLOT_CAP)]),
              ),
              t_ms: state.eeg.t_ms.slice(-PLOT_CAP),
            },
            emg: {
              channel_names: state.emg.channel_names,
              samples: Object.fromEntries(
                state.emg.channel_names.map((name) => [name, (state.emg.samples[name] ?? []).slice(-PLOT_CAP)]),
              ),
              t_ms: state.emg.t_ms.slice(-PLOT_CAP),
            },
          });
        } else if (message.type === "event") {
          // Snapshot remains source of truth; request a lightweight refresh of known fields.
        } else if (message.type === "plot") {
          const plot = message.payload as PlotSnapshot & { stream: string };
          setPlots((prev) => {
            if (plot.stream === "eeg") return { ...prev, eeg: mergePlot(prev.eeg, plot) };
            if (plot.stream === "emg") return { ...prev, emg: mergePlot(prev.emg, plot) };
            return prev;
          });
        }
      };
      ws.onclose = () => {
        setConnected(false);
        if (!cancelled) {
          retryRef.current = window.setTimeout(connect, 1000);
        }
      };
      ws.onerror = () => {
        setError("Live stream disconnected. Reconnecting…");
        ws.close();
      };
    };

    connect();
    const snapshotPoll = window.setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: "snapshot" }));
      }
    }, 1000);

    return () => {
      cancelled = true;
      window.clearInterval(snapshotPoll);
      if (retryRef.current) window.clearTimeout(retryRef.current);
      wsRef.current?.close();
    };
  }, []);

  const value = useMemo(
    () => ({ snapshot, config, connected, plots, error }),
    [snapshot, config, connected, plots, error],
  );

  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>;
}

export function useLive(): LiveContextValue {
  const ctx = useContext(LiveContext);
  if (!ctx) {
    throw new Error("useLive must be used within LiveProvider");
  }
  return ctx;
}

export function useBusyAction() {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const run = useCallback(async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setMessage(null);
    try {
      await fn();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, []);
  return { busy, message, run };
}
