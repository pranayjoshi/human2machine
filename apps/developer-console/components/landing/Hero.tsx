"use client";

import { useEffect, useRef, useState } from "react";

import { H2MLogo } from "./Logo";

/**
 * Landing hero: real footage of the desk-arm prototype as a silent background loop.
 * public/hero-loop.mp4 is cut from the Armed demo takes with the captions cropped out; nothing in it is rendered.
 */
export function Hero() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const userPaused = useRef(false);
  const [playing, setPlaying] = useState(false);

  // Safari only autoplays when the element is muted before play(); if the browser still refuses
  // (Low Power Mode, per-site autoplay settings), retry on the first click, tap, key or scroll.
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    video.muted = true;
    video.defaultMuted = true;
    video.setAttribute("muted", "");

    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    video.addEventListener("play", onPlay);
    video.addEventListener("pause", onPause);
    setPlaying(!video.paused);

    const events = ["pointerdown", "keydown", "scroll", "touchstart"] as const;
    const retry = () => {
      if (!userPaused.current) void video.play().catch(() => undefined);
      events.forEach((name) => window.removeEventListener(name, retry));
    };
    void video.play().catch(() => events.forEach((name) => window.addEventListener(name, retry, { passive: true })));

    return () => {
      video.removeEventListener("play", onPlay);
      video.removeEventListener("pause", onPause);
      events.forEach((name) => window.removeEventListener(name, retry));
    };
  }, []);

  const toggle = () => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) {
      userPaused.current = false;
      void video.play().catch(() => undefined);
    } else {
      userPaused.current = true;
      video.pause();
    }
  };

  return (
    <section className="lh-hero" id="top" aria-labelledby="lh-title">
      <video
        ref={videoRef}
        className="lh-video"
        src="/hero-loop.mp4"
        poster="/hero-poster.jpg"
        autoPlay
        muted
        loop
        playsInline
        preload="auto"
        aria-hidden="true"
      />
      <div className="lh-shade" aria-hidden="true" />

      <nav className="lh-nav" aria-label="Primary">
        <a className="lh-logo" href="#top" aria-label="H2M home">
          <H2MLogo />
        </a>
        <ul>
          <li>
            <a href="#demo">DEMO</a>
          </li>
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
            <a href="#waitlist">JOIN WAITLIST</a>
          </li>
        </ul>
      </nav>

      <div className="lh-copy">
        <h1 className="lh-title" id="lh-title">
          Human input,
          <br />
          <em>compiled.</em>
        </h1>
        <p>H2M turns speech, vision, pointing and muscle (EMG) signals into confidence-scored, safety-gated instructions for robots.</p>
        <div className="lh-actions">
          <a className="lh-btn lh-btn-primary" href="#demo">
            Watch the 1-minute demo
          </a>
          <a className="lh-btn" href="#waitlist">
            Join the pilot
          </a>
        </div>
      </div>

      <div className="lh-caption">
        <span>Real footage · SO-101 desk arm · forearm EMG band</span>
        <button type="button" className="lh-toggle" onClick={toggle} aria-label={playing ? "Pause background video" : "Play background video"}>
          {playing ? "Pause" : "Play"}
        </button>
      </div>
    </section>
  );
}
