"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { RobotSceneHandle, ScreenPoint } from "./RobotScene";
import { RobotStage } from "./RobotStage";

type StreamId = "eeg" | "emg" | "vision" | "audio" | "thermal";

type Stream = {
  id: StreamId;
  label: string;
  unit: string;
  base: number;
  range: number;
  precision: number;
  /** Anchor on the (mirrored) figure, in % of the 2:3 figure box. */
  anchor: { x: number; y: number };
  tag?: "Experimental" | "Planned";
};

// Illustrative values only — the landing page never shows live sensor data.
const STREAMS: Stream[] = [
  { id: "eeg", label: "EEG", unit: "Hz", base: 8.6, range: 0.28, precision: 1, anchor: { x: 49.7, y: 3.2 }, tag: "Experimental" },
  { id: "emg", label: "EMG", unit: "mV", base: 0.68, range: 0.08, precision: 2, anchor: { x: 65.8, y: 41.7 } },
  { id: "vision", label: "Vision", unit: "%", base: 95.9, range: 0.6, precision: 1, anchor: { x: 52.4, y: 9.6 } },
  { id: "audio", label: "Audio", unit: "dB", base: -12.1, range: 0.3, precision: 1, anchor: { x: 49.7, y: 13.3 } },
  { id: "thermal", label: "Thermal", unit: "°C", base: 36.7, range: 0, precision: 1, anchor: { x: 49.7, y: 20.5 }, tag: "Planned" },
];

const CYCLE: StreamId[] = ["emg", "vision", "audio", "eeg"];

function curve(x1: number, y1: number, x2: number, y2: number, vertical: boolean): string {
  if (vertical) {
    const dy = (y2 - y1) * 0.5;
    return `M${x1.toFixed(1)},${y1.toFixed(1)} C${x1.toFixed(1)},${(y1 + dy).toFixed(1)} ${x2.toFixed(1)},${(y2 - dy).toFixed(1)} ${x2.toFixed(1)},${y2.toFixed(1)}`;
  }
  const dx = (x2 - x1) * 0.55;
  return `M${x1.toFixed(1)},${y1.toFixed(1)} C${(x1 + dx).toFixed(1)},${y1.toFixed(1)} ${(x2 - dx).toFixed(1)},${y2.toFixed(1)} ${x2.toFixed(1)},${y2.toFixed(1)}`;
}

function Wave({ seed, tick, flat }: { seed: number; tick: number; flat?: boolean }) {
  return (
    <span className="lh-wave" aria-hidden="true">
      {Array.from({ length: 14 }, (_, index) => (
        <i key={index} style={{ height: flat ? "12%" : `${18 + ((index * 23 + seed * 7 + tick * 5) % 74)}%` }} />
      ))}
    </span>
  );
}

export function Hero() {
  const [active, setActive] = useState<StreamId>("emg");
  const [tick, setTick] = useState(0);
  const [motion, setMotion] = useState(false);

  const heroRef = useRef<HTMLElement>(null);
  const nodeRefs = useRef<Partial<Record<StreamId, HTMLSpanElement | null>>>({});
  const dotRefs = useRef<Partial<Record<StreamId, HTMLSpanElement | null>>>({});
  const beamRefs = useRef<Partial<Record<StreamId, SVGPathElement[]>>>({});
  const resultRef = useRef<HTMLDivElement>(null);
  const robotRef = useRef<HTMLDivElement>(null);
  const robotBeamRefs = useRef<SVGPathElement[]>([]);
  const robotNodeRef = useRef<SVGCircleElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const entryRef = useRef<ScreenPoint | null>(null);
  const sceneRef = useRef<RobotSceneHandle | null>(null);
  const userPicked = useRef(false);

  const values = useMemo(
    () =>
      Object.fromEntries(
        STREAMS.map((stream, index) => [stream.id, (stream.base + Math.sin((tick + index * 1.7) * 1.13) * stream.range).toFixed(stream.precision)]),
      ) as Record<StreamId, string>,
    [tick],
  );

  const layoutRobotBeam = useCallback(() => {
    const hero = heroRef.current;
    const result = resultRef.current;
    const robot = robotRef.current;
    const entry = entryRef.current;
    if (!hero || !result || !robot || !entry) return;
    const h = hero.getBoundingClientRect();
    const r = result.getBoundingClientRect();
    const v = robot.getBoundingClientRect();
    const x2 = v.left - h.left + entry.x;
    const y2 = v.top - h.top + entry.y;
    const sideBySide = v.left + v.width / 2 > r.right && v.bottom > r.top && v.top < r.bottom;
    // When the robot canvas runs under the glass panel, land the beam on the first visible
    // point of the tabletop trace to the right of the result card.
    sceneRef.current?.setEntryMinX(sideBySide ? r.right - v.left : -Infinity);
    const x1 = sideBySide ? r.right - h.left : r.left - h.left + r.width * 0.5;
    const y1 = sideBySide ? r.top - h.top + r.height * 0.5 : r.bottom - h.top;
    const d = curve(x1, y1, x2, y2, !sideBySide);
    robotBeamRefs.current.forEach((path) => path?.setAttribute("d", d));
    robotNodeRef.current?.setAttribute("cx", x2.toFixed(1));
    robotNodeRef.current?.setAttribute("cy", y2.toFixed(1));
  }, []);

  const layoutBeams = useCallback(() => {
    const hero = heroRef.current;
    if (!hero) return;
    const h = hero.getBoundingClientRect();
    svgRef.current?.setAttribute("viewBox", `0 0 ${h.width.toFixed(0)} ${h.height.toFixed(0)}`);
    for (const stream of STREAMS) {
      const node = nodeRefs.current[stream.id];
      const dot = dotRefs.current[stream.id];
      const paths = beamRefs.current[stream.id];
      if (!node || !dot || !paths) continue;
      const a = node.getBoundingClientRect();
      const b = dot.getBoundingClientRect();
      const d = curve(a.left + a.width / 2 - h.left, a.top + a.height / 2 - h.top, b.left + b.width / 2 - h.left, b.top + b.height / 2 - h.top, false);
      paths.forEach((path) => path?.setAttribute("d", d));
    }
    layoutRobotBeam();
  }, [layoutRobotBeam]);

  const onEntry = useCallback(
    (point: ScreenPoint) => {
      entryRef.current = point;
      layoutRobotBeam();
    },
    [layoutRobotBeam],
  );

  // Motion preference, value ticker and the gentle auto-cycle through prototype signals.
  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setMotion(!query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    if (!motion) return;
    let visible = true;
    const hero = heroRef.current;
    const io = hero
      ? new IntersectionObserver(([entry]) => {
          visible = entry.isIntersecting;
        })
      : null;
    if (hero) io?.observe(hero);
    const ticker = window.setInterval(() => {
      if (visible && document.visibilityState === "visible") setTick((value) => value + 1);
    }, 900);
    const cycler = window.setInterval(() => {
      if (userPicked.current || !visible || document.visibilityState !== "visible") return;
      setActive((current) => CYCLE[(CYCLE.indexOf(current) + 1) % CYCLE.length]);
    }, 3600);
    return () => {
      io?.disconnect();
      window.clearInterval(ticker);
      window.clearInterval(cycler);
    };
  }, [motion]);

  // Beam geometry follows layout, image decode, font swap and resizes.
  useEffect(() => {
    const hero = heroRef.current;
    if (!hero) return;
    const ro = new ResizeObserver(() => layoutBeams());
    ro.observe(hero);
    layoutBeams();
    void document.fonts?.ready.then(() => layoutBeams());
    return () => ro.disconnect();
  }, [layoutBeams]);

  // Pointer parallax (fine pointers only, motion allowed).
  useEffect(() => {
    const hero = heroRef.current;
    if (!hero || !motion || !window.matchMedia("(pointer: fine)").matches) return;
    let frame = 0;
    let px = 0;
    let py = 0;
    const apply = () => {
      frame = 0;
      hero.style.setProperty("--px", px.toFixed(3));
      hero.style.setProperty("--py", py.toFixed(3));
      sceneRef.current?.setPointer(px, py);
      layoutBeams();
    };
    const move = (event: PointerEvent) => {
      if (event.pointerType !== "mouse") return;
      const box = hero.getBoundingClientRect();
      px = ((event.clientX - box.left) / box.width) * 2 - 1;
      py = ((event.clientY - box.top) / box.height) * 2 - 1;
      if (!frame) frame = window.requestAnimationFrame(apply);
    };
    const leave = () => {
      px = 0;
      py = 0;
      if (!frame) frame = window.requestAnimationFrame(apply);
    };
    hero.addEventListener("pointermove", move);
    hero.addEventListener("pointerleave", leave);
    return () => {
      hero.removeEventListener("pointermove", move);
      hero.removeEventListener("pointerleave", leave);
      if (frame) window.cancelAnimationFrame(frame);
      hero.style.removeProperty("--px");
      hero.style.removeProperty("--py");
    };
  }, [motion, layoutBeams]);

  const activeStream = STREAMS.find((stream) => stream.id === active) ?? STREAMS[1];

  return (
    <section className={`lh-hero ${motion ? "lh-motion" : ""}`} id="top" ref={heroRef} aria-labelledby="lh-title">
      <div className="lh-backdrop" aria-hidden="true">
        <i className="lh-shaft" />
        <i className="lh-floor" />
        <i className="lh-fog lh-fog-a" />
        <i className="lh-fog lh-fog-b" />
      </div>

      <nav className="lh-nav" aria-label="Primary">
        <a className="lh-logo" href="#top" aria-label="H2M home">
          <strong className="h2m-wordmark">
            H<b>2</b>M
          </strong>
        </a>
        <ul>
          <li>
            <a href="#product">PRODUCT</a>
          </li>
          <li>
            <a href="#status">STATUS</a>
          </li>
          <li>
            <a href="#about">ABOUT</a>
          </li>
          <li className="lh-nav-cta">
            <a href="#waitlist">
              JOIN WAITLIST <span aria-hidden="true">↗</span>
            </a>
          </li>
        </ul>
      </nav>

      <h1 className="lh-title" id="lh-title">
        Human input,
        <br />
        <em>compiled.</em>
      </h1>

      <div className="lh-definition">
        <p>H2M turns speech, vision, pointing and muscle (EMG) signals into confidence-scored, safety-gated instructions for machines.</p>
        <span>
          <b>LOCAL-FIRST PIPELINE</b>
          <b>DETERMINISTIC SAFETY GATEWAY</b>
        </span>
      </div>

      <figure className="lh-human">
        <div className="lh-figure">
          <i className="lh-figure-glow" aria-hidden="true" />
          <i className="lh-figure-shadow" aria-hidden="true" />
          <div className="lh-figure-flip">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src="/human-skin-model.png"
              width={1024}
              height={1536}
              alt="Illustrated human figure with forearm and calf muscle detail, used to show where H2M reads input such as speech, gaze, pointing and forearm EMG"
              fetchPriority="high"
              decoding="async"
              onLoad={layoutBeams}
            />
            <i className="lh-rim lh-rim-warm" aria-hidden="true" />
            <i className="lh-rim lh-rim-cool" aria-hidden="true" />
          </div>
          <div className="lh-halo" aria-hidden="true">
            <i />
            <i />
            <b />
            <b />
            <b />
            <b />
            <b />
          </div>
          {STREAMS.map((stream) => (
            <span
              key={stream.id}
              ref={(element) => {
                nodeRefs.current[stream.id] = element;
              }}
              className={`lh-node ${active === stream.id ? "is-active" : ""} ${stream.tag === "Planned" ? "is-planned" : ""}`}
              style={{ left: `${stream.anchor.x}%`, top: `${stream.anchor.y}%` }}
              aria-hidden="true"
            />
          ))}
        </div>
      </figure>

      <div className="lh-compiler">
        <div className="lh-card lh-signals" role="group" aria-label="Signal compiler (illustrative values)">
          <header className="lh-card-head">
            <span>SIGNAL COMPILER</span>
            <span className="lh-illustrative">
              <i aria-hidden="true" /> ILLUSTRATIVE
            </span>
          </header>
          <div className="lh-rows">
            {STREAMS.map((stream, index) => {
              const planned = stream.tag === "Planned";
              return (
                <button
                  key={stream.id}
                  type="button"
                  className={`lh-row ${active === stream.id ? "is-active" : ""} ${planned ? "is-planned" : ""}`}
                  aria-pressed={active === stream.id}
                  onClick={() => {
                    userPicked.current = true;
                    setActive(stream.id);
                  }}
                >
                  <span
                    className="lh-row-dot"
                    aria-hidden="true"
                    ref={(element) => {
                      dotRefs.current[stream.id] = element;
                    }}
                  />
                  <span className="lh-row-name">
                    <b>{stream.label}</b>
                    {stream.tag ? <small className={`lh-tag lh-tag-${stream.tag.toLowerCase()}`}>{stream.tag}</small> : null}
                  </span>
                  <Wave seed={index * 11} tick={tick} flat={planned} />
                  <strong className="lh-row-value">
                    {planned ? "—" : values[stream.id]} <small>{stream.unit}</small>
                  </strong>
                </button>
              );
            })}
          </div>
          <p className="lh-note">Example values for illustration, not live sensor data.</p>
        </div>

        <div className="lh-card lh-result" ref={resultRef}>
          <small>
            MERGED SIGNAL · <b>{activeStream.label.toUpperCase()}</b> ACTIVE
          </small>
          <code>
            <span>intent</span>.pick(<b>object_03</b>)
          </code>
          <p>
            <i aria-hidden="true" /> POLICY GATED · SENT TO SIMULATOR
          </p>
        </div>
      </div>

      <div className="lh-robot" ref={robotRef}>
        <RobotStage onEntry={onEntry} sceneRef={sceneRef} />
        <p className="lh-robot-caption">
          <span>
            <i aria-hidden="true" /> ROBOT · RENDERED PREVIEW
          </span>
          <span>SIMULATOR TODAY · SO-ARM101 INTEGRATION IN DEVELOPMENT</span>
        </p>
      </div>

      <svg className="lh-beams" ref={svgRef} aria-hidden="true" focusable="false">
        <defs>
          <linearGradient id="lh-beam-grad" x1="0" x2="1" y1="0" y2="0">
            <stop offset="0" stopColor="#f07864" stopOpacity=".15" />
            <stop offset=".5" stopColor="#f07864" stopOpacity=".7" />
            <stop offset="1" stopColor="#ffb246" stopOpacity=".9" />
          </linearGradient>
        </defs>
        {STREAMS.map((stream) => (
          <g key={stream.id} className={`lh-beam ${active === stream.id ? "is-active" : ""} ${stream.tag === "Planned" ? "is-planned" : ""}`}>
            {["glow", "line", "pulse"].map((kind, index) => (
              <path
                key={kind}
                className={`lh-beam-${kind}`}
                pathLength={kind === "pulse" ? 100 : undefined}
                ref={(element) => {
                  const list = (beamRefs.current[stream.id] ??= []);
                  if (element) list[index] = element;
                }}
              />
            ))}
          </g>
        ))}
        <g className="lh-beam lh-beam-robot is-active">
          {["glow", "line", "pulse"].map((kind, index) => (
            <path
              key={kind}
              className={`lh-beam-${kind}`}
              pathLength={kind === "pulse" ? 100 : undefined}
              ref={(element) => {
                if (element) robotBeamRefs.current[index] = element;
              }}
            />
          ))}
          <circle className="lh-beam-end" r="4" ref={robotNodeRef} />
        </g>
      </svg>
    </section>
  );
}
