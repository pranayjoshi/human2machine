import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import { AppProviders } from "@/components/AppProviders";

import "./globals.css";
import "./landing-responsive.css";
import "./landing-content.css";
import "./landing-hero.css";

const siteUrl = process.env.NEXT_PUBLIC_SITE_URL ?? "https://humans2machines.com";

const organization = {
  "@context": "https://schema.org",
  "@type": "Organization",
  name: "Humans2Machines (H2M)",
  url: "https://humans2machines.com",
  logo: "https://humans2machines.com/h2m-icon.png",
  email: "pranay@humans2machines.com",
  description: "H2M is a human-to-robot intent layer that compiles speech, vision, pointing and muscle (EMG) signals into confidence-scored, safety-gated machine instructions.",
  founder: { "@type": "Person", name: "Pranay Joshi", jobTitle: "Founder" },
};

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: "Human to Machine — Human input, compiled",
  description: "H2M turns speech, vision, pointing and muscle (EMG) signals into confidence-scored, safety-gated instructions for machines.",
  icons: {
    icon: "/h2m-mark.svg",
    shortcut: "/h2m-mark.svg",
  },
  openGraph: {
    title: "H2M — Human input, compiled.",
    description: "Speech, vision, pointing and muscle signals compiled into safety-gated machine instructions.",
    type: "website",
    images: [{ url: "/og.png", width: 1200, height: 630, alt: "H2M — Human input, compiled." }],
  },
  twitter: {
    card: "summary_large_image",
    title: "H2M — Human input, compiled.",
    description: "Speech, vision, pointing and muscle signals compiled into safety-gated machine instructions.",
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
        <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(organization) }} />
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
