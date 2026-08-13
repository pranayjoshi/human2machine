"use client";

import { IntentInspector } from "@/components/IntentInspector";
import { useLive } from "@/lib/live";

export default function InspectPage() {
  const { snapshot } = useLive();
  return (
    <>
      <h1>Intent inspector</h1>
      <p className="lede">
        Every decision should remain inspectable: action, target, confidence, alternatives, evidence,
        fusion version, and the safety verdict with check results. Color is never the only signal.
      </p>
      <section className="panel">
        <IntentInspector intent={snapshot?.intent ?? null} safety={snapshot?.safety ?? null} />
      </section>
    </>
  );
}
