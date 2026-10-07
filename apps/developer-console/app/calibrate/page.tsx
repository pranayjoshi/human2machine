"use client";

import Link from "next/link";

export default function CalibrateIndexPage() {
  return (
    <>
      <header className="page-header">
        <div>
          <p className="eyebrow">Personalize</p>
          <h1>Calibration</h1>
          <p className="lede">Teach the system your setup before asking it to interpret you.</p>
        </div>
      </header>
      <div className="calibration-grid">
        <Link className="calibration-card" href="/calibrate/emg">
          <span>01</span>
          <div><p className="eyebrow">Ganglion</p><h2>Gesture model</h2><p>Learn your rest, confirm, and cancel patterns.</p></div>
          <strong>Begin →</strong>
        </Link>
        <Link className="calibration-card" href="/calibrate/vision">
          <span>02</span>
          <div><p className="eyebrow">Camera</p><h2>Workspace</h2><p>Align the table, objects, and pointing area.</p></div>
          <strong>Begin →</strong>
        </Link>
        <Link className="calibration-card" href="/calibrate/eeg">
          <span>03</span>
          <div><p className="eyebrow">Crown</p><h2>Signal quality</h2><p>Confirm clean channels and identify movement artifacts.</p></div>
          <strong>Review →</strong>
        </Link>
      </div>
    </>
  );
}
