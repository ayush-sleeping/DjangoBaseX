"use client";

/**
 * The cooldown a rate-limited error asks for (FRONTEND_PLATFORM § 3). A client module on its own:
 * errors.ts is imported by server components through api.ts and must not depend on React hooks.
 */
import { useEffect, useState } from "react";

import { isApiError } from "./errors";

/** The cooldown a rate-limited error asks for; every submit that can be throttled uses it. */
export function useCooldown(err: unknown): { disabled: boolean; secondsLeft: number } {
  const seconds = isApiError(err) && err.kind === "rate_limited" ? (err.retryAfterSeconds ?? 0) : 0;
  const [until, setUntil] = useState(0);
  const [now, setNow] = useState(0);
  // A new error object starts a new cooldown. The clock is read in callbacks, never in render.
  useEffect(() => {
    const start = setTimeout(() => {
      const at = Date.now();
      setNow(at);
      setUntil(seconds > 0 ? at + seconds * 1000 : 0);
    }, 0);
    return () => clearTimeout(start);
  }, [err, seconds]);
  useEffect(() => {
    if (until <= now) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [until, now]);
  const secondsLeft = Math.max(0, Math.ceil((until - now) / 1000));
  return { disabled: secondsLeft > 0, secondsLeft };
}
