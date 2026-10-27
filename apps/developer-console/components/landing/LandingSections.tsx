import Image from "next/image";

/**
 * Public-facing content below the hero: what H2M is, what works today, the console, and who builds it.
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
  { n: "04", title: "Act", body: "Approved commands drive a robot simulator today. Integration with a physical SO-ARM101 desk arm is in development." },
];

const STATUS: { name: string; detail: string; level: "prototype" | "experimental" | "development" | "planned" }[] = [
  { name: "Speech to intent", detail: "Live microphone, on-device speech recognition and an explicit command grammar.", level: "prototype" },
  { name: "Vision and pointing", detail: "Open-vocabulary object detection, pointing and head-direction estimation.", level: "prototype" },
  { name: "EMG gestures", detail: "OpenBCI Ganglion; a per-session calibrated rest / confirm / cancel classifier.", level: "prototype" },
  { name: "Intent fusion", detail: "Freshness- and quality-weighted late fusion with target margins and contradiction handling.", level: "prototype" },
  { name: "Safety gateway", detail: "Approve, hold or reject; confirmation, expiry, cancellation and a stop latch.", level: "prototype" },
  { name: "Robot simulator", detail: "Task-state simulator with approach, grasp and handoff, plus fault injection.", level: "prototype" },
  { name: "EEG", detail: "Recorded in shadow mode for research. It does not drive any action.", level: "experimental" },
  { name: "Physical robot arm", detail: "SO-ARM101 adapter with bounded commands and arming. Simulator-first until it passes its gates.", level: "development" },
  { name: "Thermal sensing", detail: "No thermal adapter exists yet.", level: "planned" },
];

const LEVEL_LABEL = { prototype: "Prototype", experimental: "Experimental", development: "In development", planned: "Planned" } as const;

export function LandingSections() {
  return (
    <>
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
          <p className="lc-note">
            H2M is <b>not</b> a thought reader. It estimates a small, explicit set of intents &mdash; select an object, request a handoff,
            confirm, cancel, stop &mdash; and shows how sure it is.
          </p>
        </div>
      </section>

      <section className="lc-section lc-alt" id="console" aria-labelledby="lc-console-title">
        <div className="lc-wrap">
          <p className="lc-kicker">THE CONSOLE</p>
          <h2 id="lc-console-title" className="lc-title">See every decision,<br /><em>and why it was made.</em></h2>
          <p className="lc-lede">
            The operator console shows what was heard and seen, the fused decision with its evidence, and the safety verdict, then
            streams approved commands to the robot. The captures below come from a simulated session with mock sensor data.
          </p>
          <div className="lc-shots">
            <figure>
              <div className="lc-frame">
                <div className="lc-frame-bar" aria-hidden="true"><i /><i /><i /><span>Operate</span></div>
                <Image src="/console-operate.png" alt="H2M operator console: a simulated overhead camera with detected blocks, the fused decision with evidence bars, and the safety verdict" width={2000} height={1135} sizes="(max-width: 900px) 100vw, 1100px" />
              </div>
              <figcaption><b>Operate.</b> Simulated camera view with detections, the decision, its evidence and the safety verdict.</figcaption>
            </figure>
            <figure>
              <div className="lc-frame">
                <div className="lc-frame-bar" aria-hidden="true"><i /><i /><i /><span>Robot</span></div>
                <Image src="/console-robot.png" alt="H2M robot view: a simulated six-axis desk arm on a workcell table with colored blocks, and a joint-angle readout" width={2000} height={1150} sizes="(max-width: 900px) 100vw, 1100px" />
              </div>
              <figcaption><b>Robot.</b> Simulated SO-101-style arm in a workcell, with joint angles from the simulator&rsquo;s kinematics.</figcaption>
            </figure>
          </div>
        </div>
      </section>

      <section className="lc-section" id="status" aria-labelledby="lc-status-title">
        <div className="lc-wrap">
          <p className="lc-kicker">STATUS</p>
          <h2 id="lc-status-title" className="lc-title">What works today,<br /><em>stated plainly.</em></h2>
          <p className="lc-lede">H2M is a local-first research prototype. Everything below runs against a robot simulator, and no accuracy or physical-performance claim is made yet.</p>
          <ul className="lc-status">
            {STATUS.map((row) => (
              <li key={row.name}>
                <strong>{row.name}</strong>
                <span>{row.detail}</span>
                <em className={`lc-chip lc-${row.level}`}>{LEVEL_LABEL[row.level]}</em>
              </li>
            ))}
          </ul>
          <p className="lc-note">The signal readings in the hero above are illustrative animation, not measured data.</p>
        </div>
      </section>

      <section className="lc-section lc-alt" id="about" aria-labelledby="lc-about-title">
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
                deterministic safety gate stays in control. The prototype is simulator-first, and I publish what works and what doesn&rsquo;t.
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
