"use client";

import { IntentInspector } from "@/components/IntentInspector";
import { useLive } from "@/lib/live";

export default function InspectPage() {
  const { snapshot } = useLive();
  return (
    <>
      <header className="page-header">
        <div>
          <p className="eyebrow">Decision trace</p>
          <h1>Why the system chose this.</h1>
          <p className="lede">A plain-language explanation first, with model and policy detail available when you need it.</p>
        </div>
      </header>
      <IntentInspector intent={snapshot?.intent ?? null} safety={snapshot?.safety ?? null} />
    </>
  );
}
