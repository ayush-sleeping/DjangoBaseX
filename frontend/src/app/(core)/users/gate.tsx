"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { buttonClass } from "@/core/components/Button";
import { inputClass } from "@/core/components/form/styles";
import { StatusPill } from "@/core/components/StatusPill";
import type { BootstrapUser } from "@/core/lib/bootstrap";
import type { Permissions } from "@/core/lib/permissions";

/** The class names every users screen shares, so the screens stay one family. */
export const ui = {
  card: "w-full max-w-3xl space-y-4 rounded-xl border border-border bg-card p-6 text-card-foreground",
  input: `mt-1 ${inputClass}`,
  button: buttonClass("primary"),
  danger: buttonClass("destructive"),
  quiet: "text-sm text-muted-foreground underline",
  error: "text-sm text-destructive",
};

/**
 * Loading, unreachable, signed out, not permitted, or the screen. Hides UI only: the API is the
 * decision (AUTH_BLUEPRINT § 11), and answers 403 whatever this renders.
 */
export function Gate({
  perms,
  code,
  what,
  children,
}: {
  perms: Permissions;
  /** The code the screen's main endpoint enforces. */
  code: string;
  /** "view users", "invite people": finishes "You don't have permission to …". */
  what: string;
  children: (user: BootstrapUser) => ReactNode;
}) {
  if (perms.status === "loading") return <p className="text-sm text-muted-foreground">Checking your session…</p>;
  if (perms.permissionsError && !perms.signedOut) {
    return (
      <p role="alert" className={ui.error}>
        Could not reach the server. Reload the page to try again.
      </p>
    );
  }
  if (!perms.user) {
    return (
      <section className={ui.card}>
        <p className="text-sm">Sign in to continue.</p>
        <Link className="block text-sm underline" href="/login">
          Sign in
        </Link>
      </section>
    );
  }
  if (!perms.can(code)) {
    return <p className="text-sm">You don&apos;t have permission to {what}.</p>;
  }
  return <>{children(perms.user)}</>;
}

/** Active / Deactivated, superuser and two-factor markers, through the one StatusPill. */
export function UserBadges({
  user,
}: {
  user: { is_active: boolean; is_superuser: boolean; mfa_enabled: boolean };
}) {
  return (
    <span className="inline-flex flex-wrap gap-1 align-middle">
      {user.is_active ? null : <StatusPill status="user.deactivated" />}
      {user.is_superuser ? <StatusPill status="user.superuser" title="Bypasses every permission check." /> : null}
      {user.mfa_enabled ? <StatusPill status="user.mfa_on" /> : null}
    </span>
  );
}
