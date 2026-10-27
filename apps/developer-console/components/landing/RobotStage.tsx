"use client";

import { useEffect, useRef, useState, type MutableRefObject } from "react";

import type { RobotSceneHandle, ScreenPoint } from "./RobotScene";

/**
 * Static renders of the same scene, captured from RobotScene with a transparent background:
 * "tall" matches the desktop column framing, "wide" the tablet/phone framing. Shown on first
 * paint, while three.js loads, and permanently when WebGL is unavailable, the visitor prefers
 * reduced motion, or Save-Data is on. Points are in poster pixels.
 */
const DESKTOP_QUERY = "(min-width: 1100px)";
const POSTERS = {
  tall: { src: "/robot-arm-poster-tall.webp", width: 1110, height: 1282, entry: { x: 269, y: 1107 }, label: { x: 398, y: 677 } },
  wide: { src: "/robot-arm-poster-wide.webp", width: 1520, height: 960, entry: { x: 143, y: 722 }, label: { x: 650, y: 272 } },
};
type Poster = (typeof POSTERS)["tall"];

function hasWebGL(): boolean {
  try {
    const canvas = document.createElement("canvas");
    return Boolean(canvas.getContext("webgl2") ?? canvas.getContext("webgl"));
  } catch {
    return false;
  }
}

function posterPoint(box: { width: number; height: number }, poster: Poster, point: { x: number; y: number }): ScreenPoint {
  // Mirrors `object-fit: contain; object-position: 50% 100%` on the poster image.
  const scale = Math.min(box.width / poster.width, box.height / poster.height);
  const offsetX = (box.width - poster.width * scale) / 2;
  const offsetY = box.height - poster.height * scale;
  return { x: offsetX + point.x * scale, y: offsetY + point.y * scale };
}

export function RobotStage({
  onEntry,
  sceneRef,
}: {
  onEntry: (point: ScreenPoint) => void;
  sceneRef: MutableRefObject<RobotSceneHandle | null>;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const labelRef = useRef<HTMLSpanElement>(null);
  const [live, setLive] = useState(false);
  const liveRef = useRef(false);
  const entryCb = useRef(onEntry);
  entryCb.current = onEntry;

  useEffect(() => {
    const wrap = wrapRef.current;
    const canvas = canvasRef.current;
    const label = labelRef.current;
    if (!wrap || !canvas || !label) return;

    const placePoster = () => {
      if (liveRef.current) return;
      const box = wrap.getBoundingClientRect();
      const poster = window.matchMedia(DESKTOP_QUERY).matches ? POSTERS.tall : POSTERS.wide;
      entryCb.current(posterPoint(box, poster, poster.entry));
      const tag = posterPoint(box, poster, poster.label);
      label.style.transform = `translate3d(${tag.x.toFixed(1)}px, ${tag.y.toFixed(1)}px, 0)`;
    };

    let handle: RobotSceneHandle | null = null;
    let disposed = false;
    let loading = false;
    let visible = false;
    const sync = () => handle?.setRunning(visible && document.visibilityState === "visible");

    const fallBack = () => {
      liveRef.current = false;
      setLive(false);
      placePoster();
    };

    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const saveData = Boolean((navigator as Navigator & { connection?: { saveData?: boolean } }).connection?.saveData);
    const canAnimate = !reduceMotion && !saveData && hasWebGL();

    const load = () => {
      if (loading || !canAnimate) return;
      loading = true;
      const start = () => {
        import("./RobotScene")
          .then(({ createRobotScene }) => {
            if (disposed) return;
            const box = wrap.getBoundingClientRect();
            handle = createRobotScene({
              canvas,
              label,
              compact: box.width < 700 || window.matchMedia("(pointer: coarse)").matches,
              onEntry: (point) => {
                if (liveRef.current) entryCb.current(point);
              },
              onReady: () => {
                liveRef.current = true;
                setLive(true);
              },
              onContextLost: fallBack,
            });
            sceneRef.current = handle;
            handle.resize(box.width, box.height);
            sync();
          })
          .catch((error: unknown) => {
            console.warn("H2M hero: 3D scene unavailable, showing poster.", error);
            fallBack();
          });
      };
      const idle = (window as Window & { requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => number }).requestIdleCallback;
      if (idle) idle(start, { timeout: 1500 });
      else window.setTimeout(start, 250);
    };

    const io = new IntersectionObserver(
      ([entry]) => {
        visible = entry.isIntersecting;
        if (visible) load();
        sync();
      },
      { rootMargin: "120px" },
    );
    io.observe(wrap);

    const ro = new ResizeObserver(() => {
      const box = wrap.getBoundingClientRect();
      if (handle) handle.resize(box.width, box.height);
      placePoster();
    });
    ro.observe(wrap);
    placePoster();

    document.addEventListener("visibilitychange", sync);
    return () => {
      disposed = true;
      io.disconnect();
      ro.disconnect();
      document.removeEventListener("visibilitychange", sync);
      handle?.dispose();
      handle = null;
      sceneRef.current = null;
      liveRef.current = false;
    };
  }, [sceneRef]);

  return (
    <div className={`lh-robot-view ${live ? "is-live" : ""}`} ref={wrapRef}>
      <picture className="lh-robot-poster">
        <source media={DESKTOP_QUERY} srcSet={POSTERS.tall.src} width={POSTERS.tall.width} height={POSTERS.tall.height} />
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={POSTERS.wide.src}
          width={POSTERS.wide.width}
          height={POSTERS.wide.height}
          alt="Rendered SO-ARM101-style robot arm clamped to a tabletop, carrying a block between two marked zones"
          decoding="async"
          fetchPriority="low"
        />
      </picture>
      <canvas className="lh-robot-canvas" ref={canvasRef} aria-hidden="true" />
      <span className="lh-objtag" ref={labelRef} aria-hidden="true">
        <b>object_03</b>
      </span>
    </div>
  );
}
