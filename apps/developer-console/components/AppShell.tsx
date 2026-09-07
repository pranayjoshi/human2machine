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
  { href: "/", label: "Overview", mark: "01" },
  { href: "/session", label: "Live", mark: "02" },
  { href: "/inspect", label: "Decision", mark: "03" },
  { href: "/review", label: "Sessions", mark: "04" },
  { href: "/calibrate", label: "Calibrate", mark: "05" },
  { href: "/setup", label: "Devices", mark: "06" },
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

  if (pathname === "/" || pathname === "/privacy") return <>{children}</>;

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <aside className="sidebar">
        <Link className="brand" href="/" aria-label="Human to Machine home">
          <span className="brand-mark">H/M</span>
          <span>
            <strong>Human to Machine</strong>
            <small>Intent workspace</small>
          </span>
        </Link>
        <p className="nav-label">Workspace</p>
        <nav className="nav" aria-label="Primary">
          {LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              aria-current={
                pathname === link.href ||
                (link.href !== "/" && pathname.startsWith(link.href))
                  ? "page"
                  : undefined
              }
            >
              <span>{link.mark}</span>
              {link.label}
            </Link>
          ))}
        </nav>
        <div className="sidebar-status">
          <ModeBadge mode={snapshot?.machine_mode ?? config?.machine_mode} />
          <span className={`live-dot ${connected ? "on" : ""}`}>
            <span className="mark" aria-hidden="true" />
            {connected ? "Console connected" : "Console offline"}
          </span>
          <small>Contract {SCHEMA_VERSION}</small>
        </div>
      </aside>
      <div className="app-main">
        <header className="topbar">
          <div className="session-status">
            <span className={`live-dot ${recording ? "rec" : connected ? "on" : ""}`}>
              <span className="mark" aria-hidden="true" />
              {recording ? "Session live" : session ? session.state : "Ready"}
            </span>
            {session ? (
              <span className="session-timer" aria-label={`Session timer ${formatTimer(session.started_at_ms)}`}>
                {formatTimer(session.started_at_ms)}
              </span>
            ) : null}
          </div>
          {session ? <EmergencyStop latched={Boolean(snapshot?.estop_latched)} /> : null}
        </header>
        <main id="main" className="page">
          {children}
        </main>
      </div>
      <ConfirmationModal confirmation={snapshot?.confirmation ?? null} />
    </div>
  );
}
