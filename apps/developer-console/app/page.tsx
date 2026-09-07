"use client";

import Image from "next/image";
import { FormEvent, useEffect, useMemo, useState } from "react";

const STREAMS = [
  { id: "eeg", label: "EEG", unit: "Hz", base: 8.4, precision: 1 },
  { id: "emg", label: "EMG", unit: "mV", base: 0.74, precision: 2 },
  { id: "vision", label: "Vision", unit: "%", base: 96.2, precision: 1 },
  { id: "audio", label: "Audio", unit: "dB", base: -12.4, precision: 1 },
  { id: "thermal", label: "Thermal", unit: "°C", base: 36.7, precision: 1 },
];

const WAITLIST_ENDPOINT = "https://script.google.com/macros/s/AKfycbwJqsdDgLunyxwSBdze1L9kN3lEsrgIHrJcoJ5VXdJaTEGpmr-yK7K7amNh2CSplWlu/exec";

function MiniWave({ seed, tick }: { seed: number; tick: number }) {
  return <span className="map-wave" aria-hidden="true">{Array.from({ length: 15 }, (_, index) => <i key={index} style={{ height: `${16 + ((index * 19 + seed + tick * 3) % 78)}%` }} />)}</span>;
}

export default function LandingPage() {
  const [active, setActive] = useState("eeg");
  const [tick, setTick] = useState(0);
  const [waitlistState, setWaitlistState] = useState<"idle" | "submitting" | "success" | "error">("idle");
  const [email, setEmail] = useState("");

  useEffect(() => {
    const timer = window.setInterval(() => setTick((value) => value + 1), 850);
    return () => window.clearInterval(timer);
  }, []);

  const values = useMemo(() => Object.fromEntries(STREAMS.map((stream, index) => {
    const range = stream.id === "emg" ? .08 : stream.id === "vision" ? .65 : stream.id === "thermal" ? .12 : .28;
    return [stream.id, (stream.base + Math.sin((tick + index * 1.7) * 1.13) * range).toFixed(stream.precision)];
  })), [tick]);
  async function joinWaitlist(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setWaitlistState("submitting");

    try {
      await fetch(WAITLIST_ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "text/plain;charset=utf-8" },
        body: JSON.stringify({ email, website: form.get("website") }),
        mode: "no-cors",
      });
      setWaitlistState("success");
    } catch {
      setWaitlistState("error");
    }
  }

  return (
    <main className="immersive-shell">
      <section className="immersive-hero" id="top">
        <nav className="immersive-nav" aria-label="Landing navigation">
          <a className="immersive-logo" href="#top" aria-label="H2M home"><strong className="h2m-wordmark">H<b>2</b>M</strong></a>
          <a href="#waitlist">JOIN WAITLIST ↗</a>
        </nav>

        <header className="immersive-title">
          <h1>Human input,<br /><em>compiled.</em></h1>
        </header>

        <div className="human-map" aria-label="Interactive map of human signals translated into machine intent">
          <div className="figure-aura" aria-hidden="true" />
          <Image className="map-figure biohuman-figure" src="/human-skin-model.png" alt="A mostly skin-covered female human model with localized muscle-fibre views, mapped with EEG, EMG, vision, audio, and thermal signals" width={1024} height={1536} priority />

          <div className={`neural-crown ${active === "eeg" ? "active" : ""}`} aria-hidden="true"><i /><i /><i /><i /><span /><span /><span /></div>
          <div className={`eye-beam ${active === "vision" ? "active" : ""}`} aria-hidden="true"><i /></div>
          <div className={`voice-beam ${active === "audio" ? "active" : ""}`} aria-hidden="true"><i /><i /><i /></div>
          <div className={`emg-trace ${active === "emg" ? "active" : ""}`} aria-hidden="true"><i /><i /><i /><i /></div>
          <div className={`heat-map ${active === "thermal" ? "active" : ""}`} aria-hidden="true"><i /><span>36.7</span></div>
          <div className="machine-output translation-layer" aria-label="Central translation layer compiling biological streams into machine language">
            <div className="output-head"><span>INSTRUCTION</span><i /> LIVE</div>
            <div className="compiler-streams">
              {STREAMS.map((stream, index) => (
                <button key={stream.id} type="button" className={`compiler-stream compiler-${stream.id} ${active === stream.id ? "active" : ""}`} onClick={() => setActive(stream.id)} aria-pressed={active === stream.id}>
                  <span><b>{stream.label}</b></span>
                  <MiniWave seed={index * 11} tick={tick} />
                  <strong>{values[stream.id]} <small>{stream.unit}</small></strong>
                  <i />
                </button>
              ))}
            </div>
            <div className="compiler-result" aria-live="polite">
              <small>MERGED SIGNAL · {active.toUpperCase()} ACTIVE</small>
              <code><span>intent</span>.select(<b>object_03</b>)</code>
              <p><i /> READY · POLICY GATED</p>
            </div>
            <span className="output-route" aria-hidden="true">→</span>
          </div>

          <div className="robot-destination" aria-label="Robot receiving the compiled instruction">
            <span>ROBOT</span>
            <div className="robot-figure" aria-hidden="true">
              <i className="robot-head"><b /><b /></i>
              <i className="robot-neck" />
              <i className="robot-body" />
              <i className="robot-arm robot-arm-left" />
              <i className="robot-arm robot-arm-right" />
              <i className="robot-base" />
            </div>
            <small><i /> INSTRUCTION RECEIVED</small>
          </div>
        </div>

        <div className="hero-definition">
          <p>H2M translates live EEG, EMG, vision, audio, and thermal data into machine-ready instructions.</p>
          <span><b>LOCAL-FIRST PIPELINE</b><b>DETERMINISTIC SAFETY GATEWAY</b></span>
        </div>

      </section>

      <section className="immersive-waitlist" id="waitlist">
        <div>
          <p>EARLY ACCESS</p>
          <h2>Join the first<br /><em>H2M pilot.</em></h2>
        </div>
        {waitlistState === "success" ? (
          <div className="immersive-success" role="status"><span>✓</span><div><strong>You’re on the list.</strong></div></div>
        ) : (
          <form className="immersive-form" onSubmit={joinWaitlist}>
            <label htmlFor="waitlist-email">WORK EMAIL</label>
            <input className="waitlist-trap" name="website" type="text" tabIndex={-1} autoComplete="off" aria-hidden="true" />
            <div><input id="waitlist-email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@company.com" required autoComplete="email" /><button type="submit" disabled={waitlistState === "submitting"}>{waitlistState === "submitting" ? "JOINING…" : "JOIN ↗"}</button></div>
            <small>We only use your email for pilot access. <a href="/privacy">Privacy note</a></small>
            {waitlistState === "error" ? <p className="waitlist-error" role="alert">Couldn’t save your email. Please try again.</p> : null}
          </form>
        )}
      </section>
      <footer className="immersive-footer"><strong className="h2m-wordmark">H<b>2</b>M</strong><a href="/privacy">PRIVACY</a><p>© {new Date().getFullYear()}</p></footer>
    </main>
  );
}
