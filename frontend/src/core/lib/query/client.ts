/**
 * The one QueryClient (FRONTEND_PLATFORM.md § 4): created once per browser session inside
 * useState (QueryProvider), never at module scope, which would leak one user's cache into another
 * request during SSR. Defaults are data (config/defaults.ts); a product overrides them there.
 */
import { QueryClient } from "@tanstack/react-query";

import { isApiError } from "@/core/lib/api/errors";
import { query } from "@/core/lib/config/defaults";

const RETRIABLE_STATUSES = new Set([502, 503, 504]);

/** Queries retry once, and only for network faults and 502/503/504; never a 4xx. */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (failureCount >= query.retry) return false;
  if (!isApiError(error)) return false;
  return error.kind === "network" || RETRIABLE_STATUSES.has(error.status);
}

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: query.staleTimeMs,
        gcTime: query.gcTimeMs,
        refetchOnWindowFocus: query.refetchOnWindowFocus,
        retry: shouldRetry,
      },
      mutations: { retry: 0, networkMode: "always" },
    },
  });
}
