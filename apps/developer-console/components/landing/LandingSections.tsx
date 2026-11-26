/**
 * Public-facing content below the hero: what H2M is, the demo, what works today, and who builds it.
 * Everything here describes the repository as it stands; keep it in step with docs/PERFORMANCE_ROADMAP.md.
 */
const FOUNDER = {
  name: "Pranay Joshi",
  role: "Founder",
  email: "pranay@humans2machines.com",
  // Set to the public profile URL; the link is only rendered when this is non-empty.
  linkedin: "https://linkedin.com/in/pranay-joshi-/",
};

const STEPS = [
  { n: "01", title: "Sense", body: "A microphone hears the request. A camera sees the workspace and where you point. A wrist band reads muscle (EMG) gestures such as confirm and cancel." },
  { n: "02", title: "Fuse", body: "Synchronized evidence becomes one confidence-scored intent. When the signals are weak or conflict, H2M asks “which one?” instead of guessing." },
  { n: "03", title: "Gate", body: "A deterministic safety gateway approves, holds or rejects every command. Confirmation, expiry, cancel and a stop latch sit between intent and motion." },
  { n: "04", title: "Act", body: "Approved commands drive an SO-101 desk arm, or the robot simulator for testing." },
];

const STATUS: { name: string; detail: string; level: "prototype" | "experimental" | "development" | "planned" }[] = [
  { name: "Speech to intent", detail: "Live microphone, on-device speech recognition and an explicit command grammar.", level: "prototype" },
  { name: "Vision and pointing", detail: "Open-vocabulary object detection, pointing and head-direction estimation.", level: "prototype" },
  { name: "EMG gestures", detail: "OpenBCI Ganglion; a per-session calibrated rest / confirm / cancel classifier.", level: "prototype" },
  { name: "Intent fusion", detail: "Freshness- and quality-weighted late fusion with target margins and contradiction handling.", level: "prototype" },
  { name: "Safety gateway", detail: "Approve, hold or reject; confirmation, expiry, cancellation and a stop latch.", level: "prototype" },
  { name: "Physical robot arm", detail: "SO-101 desk arm doing handoffs, holds and desk clearing in the demo above. Not yet tested beyond my desk.", level: "prototype" },
  { name: "EEG", detail: "Recorded in shadow mode for research. It does not drive any action.", level: "experimental" },
];

const LEVEL_LABEL = { prototype: "Prototype", experimental: "Experimental", development: "In development", planned: "Planned" } as const;

export function LandingSections() {
  return (
    <>
      <section className="lc-section lc-alt" id="demo" aria-labelledby="lc-demo-title">
        <div className="lc-wrap">
          <p className="lc-kicker">DEMO</p>
          <h2 id="lc-demo-title" className="lc-title">One day with a<br /><em>third arm.</em></h2>
          <p className="lc-lede">
            Armed, the desk-arm prototype: it sees what I need, asks, and waits for a muscle activation in my forearm before it moves.
          </p>
          <div className="lc-video">
            <video src="/armed-demo-720p.mp4" poster="/armed-demo-poster.jpg" controls playsInline preload="none" />
          </div>
          <p className="lc-video-caption">
            Filmed at my desk for the Meta AI hackathon, November 2026. The mid-air stop take used an injected brace signal rather than
            one read from the band.
          </p>
        </div>
      </section>

      <section className="lc-section" id="product" aria-labelledby="lc-product-title">
        <div className="lc-wrap">
          <p className="lc-kicker">WHAT H2M IS</p>
          <h2 id="lc-product-title" className="lc-title">A human-to-robot intent layer,<br /><em>with a safety gate.</em></h2>
          <p className="lc-lede">
            People communicate naturally; machines need precise, safe instructions. H2M listens to what you say, sees what you point at and
            reads your muscle effort, then compiles those signals into one machine-readable instruction with an honest confidence score.
          </p>
          <ol className="lc-steps">
            {STEPS.map((step) => (
              <li key={step.n}>
                <span className="lc-step-n">{step.n}</span>
                <h3>{step.title}</h3>
                <p>{step.body}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="lc-section lc-alt" id="status" aria-labelledby="lc-status-title">
        <div className="lc-wrap">
          <p className="lc-kicker">STATUS</p>
          <h2 id="lc-status-title" className="lc-title">What works today,<br /><em>stated plainly.</em></h2>
          <p className="lc-lede">H2M is a local-first research prototype. No accuracy or reliability claim is made yet.</p>
          <ul className="lc-status">
            {STATUS.map((row) => (
              <li key={row.name}>
                <strong>{row.name}</strong>
                <span>{row.detail}</span>
                <em className={`lc-chip lc-${row.level}`}>{LEVEL_LABEL[row.level]}</em>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className="lc-section" id="about" aria-labelledby="lc-about-title">
        <div className="lc-wrap lc-about">
          <div>
            <p className="lc-kicker">ABOUT</p>
            <h2 id="lc-about-title" className="lc-title">Built by one founder,<br /><em>in the open.</em></h2>
          </div>
          <div className="lc-person">
            <div className="lc-avatar" aria-hidden="true">{FOUNDER.name.split(" ").map((part) => part[0]).join("")}</div>
            <div>
              <h3>{FOUNDER.name}</h3>
              <p className="lc-role">{FOUNDER.role}, H2M</p>
              <p>
                I&rsquo;m building H2M, an intent layer that lets people direct robots with speech, gesture and muscle signals while a
                deterministic safety gate stays in control. The prototype runs on a real desk arm, and I publish what works and what doesn&rsquo;t.
              </p>
              <p className="lc-links">
                <a href={`mailto:${FOUNDER.email}`}>{FOUNDER.email}</a>
                {FOUNDER.linkedin ? <a href={FOUNDER.linkedin} rel="noopener noreferrer" target="_blank">LinkedIn &nearr;</a> : null}
              </p>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
