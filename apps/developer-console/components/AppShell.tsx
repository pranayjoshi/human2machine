"use client";

import { SCHEMA_VERSION } from "@intent/contracts";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { ConfirmationModal } from "@/components/ConfirmationModal";
import { EmergencyStop } from "@/components/EmergencyStop";
import { ModeBadge } from "@/components/ModeBadge";
import { useLive } from "@/lib/live";

const LINKS = [
  { href: "/", label: "Preflight" },
  { href: "/session", label: "Live session" },
  { href: "/inspect", label: "Intent inspector" },
  { href: "/review", label: "Session review" },
];

function formatTimer(startedAt?: number | null): string {
  if (!startedAt) return "00:00";
  const elapsed = Math.max(0, Date.now() - startedAt);
  const minutes = Math.floor(elapsed / 60000);
  const seconds = Math.floor((elapsed % 60000) / 1000);
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { snapshot, config, connected } = useLive();
  const session = snapshot?.session ?? null;
  const recording = session?.state === "RECORDING";

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="topbar">
        <div className="brand">Intent compiler · v{SCHEMA_VERSION}</div>
        <nav className="nav" aria-label="Primary">
          {LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              aria-current={pathname === link.href ? "page" : undefined}
            >
              {link.label}
            </Link>
          ))}
        </nav>
        <div className="topbar-status">
          <span className={`live-dot ${connected ? "on" : ""}`}>
            <span className="mark" aria-hidden="true" />
            {connected ? "Live stream connected" : "Live stream disconnected"}
          </span>
          {session ? (
            <>
              <span className={`live-dot ${recording ? "rec" : ""}`}>
                <span className="mark" aria-hidden="true" />
                {recording ? "Recording" : session.state}
              </span>
              <span aria-label={`Session timer ${formatTimer(session.started_at_ms)}`}>
                {formatTimer(session.started_at_ms)}
              </span>
            </>
          ) : null}
          <ModeBadge mode={snapshot?.machine_mode ?? config?.machine_mode} />
          {session ? <EmergencyStop latched={Boolean(snapshot?.estop_latched)} /> : null}
        </div>
      </header>
      <main id="main" className="page">
        {children}
      </main>
      <ConfirmationModal confirmation={snapshot?.confirmation ?? null} />
    </div>
  );
}
