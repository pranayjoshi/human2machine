"use client";

import { FormEvent, useState } from "react";

import { Hero } from "@/components/landing/Hero";
import { LandingSections } from "@/components/landing/LandingSections";

const WAITLIST_ENDPOINT = "https://script.google.com/macros/s/AKfycbwJqsdDgLunyxwSBdze1L9kN3lEsrgIHrJcoJ5VXdJaTEGpmr-yK7K7amNh2CSplWlu/exec";

export default function LandingPage() {
  const [waitlistState, setWaitlistState] = useState<"idle" | "submitting" | "success" | "error">("idle");
  const [email, setEmail] = useState("");

  async function joinWaitlist(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setWaitlistState("submitting");

    try {
      await fetch(WAITLIST_ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "text/plain;charset=utf-8" },
        body: JSON.stringify({ email, website: form.get("website") }),
        mode: "no-cors",
      });
      setWaitlistState("success");
    } catch {
      setWaitlistState("error");
    }
  }

  return (
    <main className="immersive-shell">
      <Hero />

      <LandingSections />

      <section className="immersive-waitlist" id="waitlist">
        <div>
          <p>EARLY ACCESS</p>
          <h2>Join the first<br /><em>H2M pilot.</em></h2>
        </div>
        {waitlistState === "success" ? (
          <div className="immersive-success" role="status"><span>✓</span><div><strong>You’re on the list.</strong></div></div>
        ) : (
          <form className="immersive-form" onSubmit={joinWaitlist}>
            <label htmlFor="waitlist-email">WORK EMAIL</label>
            <input className="waitlist-trap" name="website" type="text" tabIndex={-1} autoComplete="off" aria-hidden="true" />
            <div><input id="waitlist-email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@company.com" required autoComplete="email" /><button type="submit" disabled={waitlistState === "submitting"}>{waitlistState === "submitting" ? "JOINING…" : "JOIN ↗"}</button></div>
            <small>We only use your email for pilot access. <a href="/privacy">Privacy note</a></small>
            {waitlistState === "error" ? <p className="waitlist-error" role="alert">Couldn’t save your email. Please try again.</p> : null}
          </form>
        )}
      </section>
      <footer className="immersive-footer"><strong className="h2m-wordmark">H<b>2</b>M</strong><nav className="lc-footer-links" aria-label="Footer"><a href="#product">PRODUCT</a><a href="#status">STATUS</a><a href="#about">ABOUT</a><a href="mailto:pranay@humans2machines.com">CONTACT</a><a href="/privacy">PRIVACY</a></nav><p>© {new Date().getFullYear()} H2M</p></footer>
    </main>
  );
}
