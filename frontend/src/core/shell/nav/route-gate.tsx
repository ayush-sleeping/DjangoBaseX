"use client";

/**
 * Navigation is the route gate (FRONTEND_PLATFORM § 10, BUILD_ORDER 8.2). Every page under the
 * portal layout is matched to its navigation entry by resolveRoute() — the deepest prefix — and:
 *
 * - no entry          → denied (default-deny): a page nobody registered is not reachable by URL;
 * - a public entry    → rendered, signed in or not;
 * - lacking its code  → the denied card instead of the page.
 *
 * Entries come from the generated manifest (every core page, gated or not) plus the user's own
 * bootstrap `nav` (a linked plugin's pages). The manifest is consulted first so a filtered-out
 * entry can never fall back to a shallower one the user does hold (/users/new → /users).
 *
 * This hides pages; it does not protect data. Every endpoint behind a page decides for itself.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { useBootstrap } from "@/core/lib/bootstrap";
import { DeniedCard, type Permissions, usePermissions } from "@/core/lib/permissions";

import { MANIFEST_ENTRIES } from "./manifest";
import { flatten, resolveRoute, type RouteEntry } from "./resolve-route";

export type GateDecision =
  | { kind: "allow"; entry: RouteEntry }
  | { kind: "loading" }
  | { kind: "signed-out" }
  | { kind: "error" }
  | { kind: "no-entry" }
  | { kind: "denied"; entry: RouteEntry };

export function decide(
  pathname: string,
  perms: Pick<Permissions, "status" | "signedOut" | "can">,
  userEntries: readonly RouteEntry[],
): GateDecision {
  const entry = resolveRoute(pathname, [...MANIFEST_ENTRIES, ...userEntries]);
  if (entry?.public) return { kind: "allow", entry };
  if (perms.status === "loading") return { kind: "loading" };
  if (perms.status === "error") return perms.signedOut ? { kind: "signed-out" } : { kind: "error" };
  if (!entry) return { kind: "no-entry" };
  if (entry.permission !== null && !perms.can(entry.permission)) return { kind: "denied", entry };
  return { kind: "allow", entry };
}

/** Called before any early return in the layout: hooks order must never depend on the outcome. */
export function useRouteGate(): GateDecision & { retry: () => Promise<void> } {
  const pathname = usePathname() ?? "/";
  const perms = usePermissions();
  const boot = useBootstrap();
  const userEntries = boot.data?.nav ? flatten(boot.data.nav) : [];
  return { ...decide(pathname, perms, userEntries), retry: perms.retry };
}

export function RouteGate({ children }: { children: ReactNode }) {
  const gate = useRouteGate();
  switch (gate.kind) {
    case "allow":
      return <>{children}</>;
    case "loading":
      return <p className="p-8 text-sm text-zinc-500">Checking your session…</p>;
    case "signed-out":
      return (
        <section className="p-8 text-sm">
          <p>Sign in to continue.</p>
          <Link className="underline" href="/login">
            Sign in
          </Link>
        </section>
      );
    case "error":
      return (
        <section role="alert" className="p-8 text-sm text-red-600">
          <p>Could not load your permissions, so nothing is shown.</p>
          <button type="button" className="underline" onClick={() => void gate.retry()}>
            Try again
          </button>
        </section>
      );
    case "no-entry":
    case "denied":
      return (
        <section className="p-8">
          <DeniedCard what="open this page" />
        </section>
      );
  }
}
