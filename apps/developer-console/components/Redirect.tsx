"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

/** Client-side redirect; the console is a static export so server redirects are unavailable. */
export function Redirect({ to }: { to: string }) {
  const router = useRouter();
  useEffect(() => {
    router.replace(to);
  }, [router, to]);
  return <p className="muted">Moved — opening {to}…</p>;
}
