/**
 * GET /api/me/bootstrap/ — the shell's one round trip after sign-in (FRONTEND_PLATFORM § 7,
 * BUILD_ORDER 8.2). One cached query feeds the permission provider, the menu and the route gate,
 * so all three read the same answer.
 *
 * `permissions` is the EFFECTIVE set (superuser already expanded) computed by the same backend
 * function as has_perm(); the frontend never special-cases a bypass. `degraded` lists decorative
 * sections that failed on the server and were left out.
 */
import type { StatusMeta } from "@/generated/statuses";

import { api } from "./api";
import type { NavSection } from "@/core/shell/nav/resolve-route";
import { defineKeys } from "./query/keys";
import { useApiQuery } from "./query/use-api-query";

export type BootstrapUser = {
  public_id: string;
  email: string;
  full_name: string;
  is_staff: boolean;
  is_superuser: boolean;
  mfa_enabled: boolean;
  mfa_enforced: boolean;
};

export type Bootstrap = {
  user: BootstrapUser;
  permissions: string[];
  session: { expires_at: string; idle_expires_at: string };
  server_time: string;
  nav?: NavSection[];
  flags?: string[];
  /** Every app's status metadata, linked plugins included (decorative). */
  statuses?: Record<string, StatusMeta>;
  build?: string;
  degraded: string[];
};

export const bootstrapKeys = defineKeys("me.bootstrap", { current: () => ["current"] });

export function fetchBootstrap(signal?: AbortSignal): Promise<Bootstrap> {
  return api<Bootstrap>("/api/me/bootstrap/", { cache: "no-store", signal });
}

/** Refetched when invalidated (identity or permission change), not on focus or reconnect. */
export function useBootstrap() {
  return useApiQuery<Bootstrap>(bootstrapKeys.current(), fetchBootstrap, {
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
}
