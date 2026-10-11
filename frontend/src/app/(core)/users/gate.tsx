"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import type { Me } from "@/core/lib/auth";
import type { Permissions } from "@/core/lib/permissions";

/** The class names every users screen shares, so the screens stay one family. */
export const ui = {
  card: "w-full max-w-3xl space-y-4 rounded-xl border border-zinc-200 p-6 dark:border-zinc-800",
  input:
    "mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 disabled:opacity-60 dark:border-zinc-700 dark:bg-zinc-900",
  button:
    "rounded-md bg-zinc-900 px-3 py-2 text-sm text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900",
  danger: "rounded-md bg-red-600 px-3 py-2 text-sm text-white disabled:opacity-50",
  quiet: "text-sm text-zinc-500 underline",
  error: "text-sm text-red-600",
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
  children: (me: Me) => ReactNode;
}) {
  if (perms.loading) return <p className="text-sm text-zinc-500">Checking your session…</p>;
  if (perms.failed) {
    return (
      <p role="alert" className={ui.error}>
        Could not reach the server. Reload the page to try again.
      </p>
    );
  }
  if (!perms.me) {
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
  return <>{children(perms.me)}</>;
}

/** Active / Deactivated, superuser and two-factor markers. */
export function UserBadges({
  user,
}: {
  user: { is_active: boolean; is_superuser: boolean; mfa_enabled: boolean };
}) {
  const badge = "rounded px-1.5 py-0.5 text-xs";
  return (
    <span className="inline-flex flex-wrap gap-1 align-middle">
      {user.is_active ? null : (
        <span className={`${badge} bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300`}>
          Deactivated
        </span>
      )}
      {user.is_superuser ? (
        <span
          className={`${badge} bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300`}
          title="Bypasses every permission check."
        >
          Superuser
        </span>
      ) : null}
      {user.mfa_enabled ? (
        <span className={`${badge} bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300`}>
          Two-factor on
        </span>
      ) : null}
    </span>
  );
}
