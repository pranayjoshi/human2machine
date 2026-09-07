import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import { AppShell } from "@/components/AppShell";
import { LiveProvider } from "@/lib/live";

import "./globals.css";
import "./landing-responsive.css";

const siteUrl = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3001";

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: "Human to Machine — Human input, compiled",
  description: "H2M translates live EEG, EMG, vision, audio, and thermal data into machine-ready instructions.",
  icons: {
    icon: "/h2m-mark.svg",
    shortcut: "/h2m-mark.svg",
  },
  openGraph: {
    title: "H2M — Human input, compiled.",
    description: "Live human signals translated into machine-ready instructions.",
    type: "website",
    images: [{ url: "/og.png", width: 1200, height: 630, alt: "H2M — Human input, compiled." }],
  },
  twitter: {
    card: "summary_large_image",
    title: "H2M — Human input, compiled.",
    description: "Live human signals translated into machine-ready instructions.",
    images: ["/og.png"],
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
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
