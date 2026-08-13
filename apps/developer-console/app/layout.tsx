import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AppShell } from "@/components/AppShell";
import { LiveProvider } from "@/lib/live";

import "./globals.css";

export const metadata: Metadata = {
  title: "Developer console",
  description: "Multimodal intent compiler operator console",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <LiveProvider>
          <AppShell>{children}</AppShell>
        </LiveProvider>
      </body>
    </html>
  );
}
