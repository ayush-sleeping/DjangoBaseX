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
import { useT } from "@/core/lib/i18n";
import { DeniedCard, type PermissionCode, type Permissions, usePermissions } from "@/core/lib/permissions";

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
  // The code is data from the server's own navigation (a plugin's included), not a literal in
  // source, so the compile-time PermissionCode check cannot apply: it is checked as the server sent it.
  if (entry.permission !== null && !perms.can(entry.permission as PermissionCode)) return { kind: "denied", entry };
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
  const t = useT("shell.gate");
  const common = useT("common");
  const gate = useRouteGate();
  switch (gate.kind) {
    case "allow":
      return <>{children}</>;
    case "loading":
      return <p className="p-8 text-sm text-muted-foreground">{t("checking")}</p>;
    case "signed-out":
      return (
        <section className="p-8 text-sm">
          <p>{t("signInPrompt")}</p>
          <Link className="underline" href="/login">
            {t("signIn")}
          </Link>
        </section>
      );
    case "error":
      return (
        <section role="alert" className="p-8 text-sm text-destructive">
          <p>{t("permissionsFailed")}</p>
          <button type="button" className="underline" onClick={() => void gate.retry()}>
            {common("tryAgain")}
          </button>
        </section>
      );
    case "no-entry":
    case "denied":
      return (
        <section className="p-8">
          <DeniedCard what={t("openThisPage")} />
        </section>
      );
  }
}
