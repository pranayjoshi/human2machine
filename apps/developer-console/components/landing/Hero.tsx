"use client";

import { useEffect, useRef } from "react";

import { H2MLogo } from "./Logo";

/**
 * Landing hero: real footage of the desk-arm prototype as a silent background loop.
 * public/hero-loop.mp4 is cut from the Armed demo takes with the captions cropped out; nothing in it is rendered.
 */
export function Hero() {
  const videoRef = useRef<HTMLVideoElement>(null);

  // Respect reduced motion: keep the poster frame instead of autoplaying.
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => {
      if (query.matches) video.pause();
      else void video.play().catch(() => undefined);
    };
    sync();
    query.addEventListener("change", sync);
    return () => query.removeEventListener("change", sync);
  }, []);

  return (
    <section className="lh-hero" id="top" aria-labelledby="lh-title">
      <video
        ref={videoRef}
        className="lh-video"
        src="/hero-loop.mp4"
        poster="/hero-poster.jpg"
        muted
        loop
        playsInline
        preload="metadata"
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

      <p className="lh-caption">Real footage · SO-101 desk arm · forearm EMG band</p>
    </section>
  );
}
