/**
 * Transport and query defaults (FRONTEND_PLATFORM.md §§ 2, 4). Data, in one place; a product
 * overrides them from src/project/config.ts, never by editing core.
 */
export const transport = {
  /** Every call, unless `longTimeout` is asked for (exports, reports). */
  timeoutMs: 15_000,
  longTimeoutMs: 120_000,
  /** A bad Retry-After header must not wedge a button for a day. */
  maxRetryAfterSeconds: 3600,
} as const;

export const query = {
  staleTimeMs: 60_000,
  gcTimeMs: 5 * 60_000,
  /** Queries retry once, and only for network faults and 502/503/504; never a 4xx. */
  retry: 1,
  refetchOnWindowFocus: false,
} as const;

export const poll = {
  transitionalIntervalMs: 3000,
} as const;
