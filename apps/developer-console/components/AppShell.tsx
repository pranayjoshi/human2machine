"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { ConfirmationModal } from "@/components/ConfirmationModal";
import { EmergencyStop } from "@/components/EmergencyStop";
import { elapsed } from "@/lib/format";
import { useLive } from "@/lib/live";

const LINKS = [
  { href: "/session", label: "Operate", hint: "Run sessions and watch decisions" },
  { href: "/setup", label: "Setup", hint: "Devices, calibration, preflight" },
  { href: "/testing", label: "Robot", hint: "Live machine state" },
  { href: "/review", label: "Sessions", hint: "Recorded history" },
];

const ACTIVE_ALIASES: Record<string, string> = {
  "/inspect": "/session",
  "/calibrate": "/setup",
};

function activeHref(pathname: string): string {
  for (const [prefix, target] of Object.entries(ACTIVE_ALIASES)) {
    if (pathname.startsWith(prefix)) return target;
  }
  return LINKS.find((link) => pathname.startsWith(link.href))?.href ?? "";
}

function useNow(enabled: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!enabled) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [enabled]);
  return now;
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { snapshot, config, connected } = useLive();
  const session = snapshot?.session ?? null;
  const recording = session?.state === "RECORDING";
  const now = useNow(Boolean(session));

  if (pathname === "/" || pathname === "/privacy") return <>{children}</>;

  const current = activeHref(pathname);
  const mode = snapshot?.machine_mode ?? config?.machine_mode ?? "simulator_only";
  const physical = /physical/i.test(mode) && !/simulator/i.test(mode);
  const mock = snapshot?.mock ?? config?.mock ?? false;

  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="shell-bar">
        <Link className="shell-brand" href="/" aria-label="Human to Machine home">
          <span className="brand-mark">H/M</span>
          <strong>Human to Machine</strong>
        </Link>
        <nav className="shell-nav" aria-label="Primary">
          {LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              title={link.hint}
              aria-current={current === link.href ? "page" : undefined}
            >
              {link.label}
            </Link>
          ))}
        </nav>
        <div className="shell-status">
          <span className={`chip ${connected ? "chip-ok" : "chip-bad"}`}>
            <i aria-hidden="true" />
            {connected ? "Connected" : "Offline"}
          </span>
          {mock ? <span className="chip chip-warn" title="Started with --mock: no real devices">Mock stack</span> : null}
          <span className={`chip ${physical ? "chip-bad" : ""}`}>{physical ? "Robot armed" : "Simulator"}</span>
          {session ? (
            <span className={`chip ${recording ? "chip-rec" : ""}`}>
              <i aria-hidden="true" />
              {recording ? "Recording" : words(session.state)} · {elapsed(session.started_at_ms, now)}
            </span>
          ) : null}
          <EmergencyStop latched={Boolean(snapshot?.estop_latched)} />
        </div>
      </header>
      <main id="main" className="shell-page">
        {children}
      </main>
      <ConfirmationModal confirmation={snapshot?.confirmation ?? null} />
    </div>
  );
}

function words(value: string): string {
  return value.replaceAll("_", " ").toLowerCase().replace(/^\w/, (letter) => letter.toUpperCase());
}
