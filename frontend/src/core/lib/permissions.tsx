"use client";

/**
 * The permission provider (FRONTEND_PLATFORM § 9, BUILD_ORDER 8.2): what the signed-in user may
 * see, from bootstrap's EFFECTIVE permission set. These only HIDE UI: every check is re-made by
 * the API, which answers 403 whatever the screen shows (AUTH_BLUEPRINT § 11).
 *
 * FAIL CLOSED. While loading, on any fetch error, and outside a provider, can() is false for every
 * code. A failed fetch sets `permissionsError` — a REQUIRED field, so a page that reads the
 * provider cannot miss that it exists — and the page shows a retry path, never broad controls.
 *
 * Affordance parity: gate each control on EXACTLY the code its endpoint enforces (the *_CODES maps
 * beside each API module, e.g. ROLE_CODES in ./rbac), never on a broad flag. The provider has no
 * isAdmin: `user.is_superuser` is already folded into `permissions` by the backend.
 */
import { createContext, type ReactNode, useContext, useMemo } from "react";

import { isApiError } from "./api";
import { type BootstrapUser, useBootstrap } from "./bootstrap";

export type PermissionStatus = "loading" | "ready" | "error";

export type Permissions = {
  status: PermissionStatus;
  /** Non-null exactly when status is "error". Pages must render a retry path for it. */
  permissionsError: unknown;
  /** The fetch failed because nobody is signed in (a 401 the refresh could not recover). */
  signedOut: boolean;
  /** Who is signed in; null unless status is "ready". */
  user: BootstrapUser | null;
  can: (code: string) => boolean;
  canAny: (codes: readonly string[]) => boolean;
  canAll: (codes: readonly string[]) => boolean;
  /** Fetch bootstrap again (the retry path). */
  retry: () => Promise<void>;
};

const deny = () => false;

/** Everything denied: a missing provider and a failed fetch both look like this. */
export const DENY_ALL: Permissions = {
  status: "loading",
  permissionsError: null,
  signedOut: false,
  user: null,
  can: deny,
  canAny: deny,
  canAll: deny,
  retry: async () => {},
};

const Ctx = createContext<Permissions | null>(null);

export function permissionsFrom(codes: readonly string[]) {
  const held = new Set(codes);
  const can = (code: string) => held.has(code);
  return {
    can,
    canAny: (list: readonly string[]) => list.some(can),
    // An empty list grants nothing: "all of none" must not open a gate by accident.
    canAll: (list: readonly string[]) => list.length > 0 && list.every(can),
  };
}

export function PermissionProvider({ children }: { children: ReactNode }) {
  const boot = useBootstrap();
  const value = useMemo<Permissions>(() => {
    if (boot.data && !boot.showError) {
      return {
        ...permissionsFrom(boot.data.permissions),
        status: "ready",
        permissionsError: null,
        signedOut: false,
        user: boot.data.user,
        retry: boot.refetch,
      };
    }
    if (boot.isError) {
      return {
        ...DENY_ALL,
        status: "error",
        permissionsError: boot.error ?? new Error("permissions unavailable"),
        signedOut: isApiError(boot.error) && boot.error.status === 401,
        retry: boot.refetch,
      };
    }
    return { ...DENY_ALL, retry: boot.refetch };
  }, [boot.data, boot.showError, boot.isError, boot.error, boot.refetch]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/** The provider's answer. Throws outside a provider: a page must not run ungated by accident. */
export function usePermissions(): Permissions {
  const value = useContext(Ctx);
  if (!value) throw new Error("usePermissions() outside <PermissionProvider>");
  return value;
}

/** For shared components that may render outside the shell: no provider → everything denied. */
export function useOptionalPermissions(): Permissions {
  return useContext(Ctx) ?? DENY_ALL;
}

/**
 * Renders `children` only when `perm` is held. Loading renders nothing; denied renders a VISIBLE
 * card (or `fallback`), so denied never looks like empty or like loading.
 */
export function Can({ perm, fallback, children }: { perm: string; fallback?: ReactNode; children: ReactNode }) {
  const perms = useOptionalPermissions();
  if (perms.status === "loading") return null;
  if (perms.can(perm)) return <>{children}</>;
  return fallback !== undefined ? <>{fallback}</> : <DeniedCard />;
}

export function DeniedCard({ what = "view this section" }: { what?: string }) {
  return (
    <p role="status" className="rounded-md border border-border p-4 text-sm">
      You don&apos;t have permission to {what}.
    </p>
  );
}
