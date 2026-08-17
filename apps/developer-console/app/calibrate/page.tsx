"use client";

import Link from "next/link";

export default function CalibrateIndexPage() {
  return (
    <>
      <h1>Calibration</h1>
      <p className="lede">
        Guided EMG, vision, and EEG checks. EMG is the only path that can later drive confirm/cancel.
        EEG stays shadow-only. Promoted models belong under <code>models/</code>, not in Git.
      </p>
      <div className="grid-2">
        <section className="panel">
          <h2>
            <Link href="/calibrate/emg">EMG (Ganglion)</Link>
          </h2>
          <p>Rest 30s, confirm ×20, cancel ×20, randomized block, train, then a false-trigger rest trial.</p>
        </section>
        <section className="panel">
          <h2>
            <Link href="/calibrate/vision">Vision (camera)</Link>
          </h2>
          <p>Camera index, table workspace, four object IDs, pointing test. Acknowledge when done.</p>
        </section>
        <section className="panel">
          <h2>
            <Link href="/calibrate/eeg">EEG (Crown, shadow)</Link>
          </h2>
          <p>Connection and motion-artifact notes. EEG is shadow-only and never drives action.</p>
        </section>
      </div>
    </>
  );
}
