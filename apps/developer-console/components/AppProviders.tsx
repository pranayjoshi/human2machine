"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { AppShell } from "@/components/AppShell";
import { LiveProvider } from "@/lib/live";

const PUBLIC_PATHS = new Set(["/", "/privacy"]);

/**
 * The public landing page and privacy note are static: they must not poll the local console API
 * (127.0.0.1:8000), which does not exist on the published site. Console pages get the live provider.
 */
export function AppProviders({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "/";
  const normalized = pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
  if (PUBLIC_PATHS.has(normalized)) return <>{children}</>;
  return (
    <LiveProvider>
      <AppShell>{children}</AppShell>
    </LiveProvider>
  );
}
