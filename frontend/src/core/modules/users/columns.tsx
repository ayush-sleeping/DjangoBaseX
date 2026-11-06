"use client";

/**
 * Columns for the Users and Invitations indexes, in the fixed order (FRONTEND_PLATFORM § 11):
 * identifier → status → data → actions. No sortKey: the users and invitations endpoints accept no
 * `ordering`, and an arrow that does nothing is a lie.
 *
 * Hooks, not constants: headers and cells carry the viewer's translated copy (§ 22).
 */
import { Ban, ChevronRight } from "lucide-react";
import Link from "next/link";
import { type ReactNode, useMemo } from "react";

import { buttonClass, IconButton } from "@/core/components/Button";
import type { DataTableColumn } from "@/core/components/data-table";
import { DateTime } from "@/core/components/format";
import { StatusPill } from "@/core/components/StatusPill";
import { EMPTY } from "@/core/lib/format";
import { useT } from "@/core/lib/i18n";
import type { Invitation } from "@/core/lib/invitations";
import type { User } from "@/core/lib/users";

export const userHref = (publicId: string) => `/users/${encodeURIComponent(publicId)}`;
export const userLabel = (user: User) => user.full_name || user.email;

export function useUserColumns(): DataTableColumn<User>[] {
  const t = useT("users.columns");
  const common = useT("common");
  return useMemo(
    () => [
      {
        id: "user",
        kind: "identifier",
        header: t("user"),
        cell: (user) => (
          <div className="min-w-0">
            <Link className="font-medium underline-offset-4 hover:underline" href={userHref(user.public_id)}>
              {user.email}
            </Link>
            {user.full_name ? <span className="block truncate text-xs text-muted-foreground">{user.full_name}</span> : null}
          </div>
        ),
      },
      {
        id: "status",
        kind: "status",
        header: common("status"),
        cell: (user) => (
          <span className="inline-flex flex-wrap gap-1">
            <StatusPill status={user.is_active ? "users.user.active" : "users.user.deactivated"} />
            {user.is_superuser ? <StatusPill status="users.user.superuser" title={t("superuser")} /> : null}
          </span>
        ),
      },
      {
        id: "roles",
        kind: "data",
        header: t("roles"),
        hideBelow: "md",
        cell: (user) => <span className="text-xs">{user.roles.map((role) => role.name).join(", ") || EMPTY}</span>,
      },
      {
        id: "mfa",
        kind: "data",
        header: t("twoFactor"),
        hideBelow: "lg",
        cell: (user) => (user.mfa_enabled ? <StatusPill status="users.user.mfa_on" /> : <span className="text-xs text-muted-foreground">{t("off")}</span>),
      },
      {
        id: "last_login",
        kind: "data",
        header: t("lastSignIn"),
        hideBelow: "sm",
        cell: (user) => (
          <span className="text-xs text-muted-foreground">
            <DateTime value={user.last_login} />
          </span>
        ),
      },
      {
        id: "actions",
        kind: "actions",
        header: <span className="sr-only">{common("actions")}</span>,
        width: "3.5rem",
        cell: (user) => (
          <Link href={userHref(user.public_id)} aria-label={t("openUser", { name: userLabel(user) })} title={t("open")} className={buttonClass("ghost", "sm", "w-8 px-0")}>
            <ChevronRight aria-hidden className="size-4" />
          </Link>
        ),
      },
    ],
    [t, common],
  );
}

/** `onRevoke` undefined → no revoke button: a control nobody authorised is never drawn (§ 9). */
export function useInvitationColumns({ onRevoke, revoking }: { onRevoke?: (i: Invitation) => void; revoking?: string }): DataTableColumn<Invitation>[] {
  const t = useT("users.invitations");
  const common = useT("common");
  return useMemo(() => {
    // The <date></date> tag of a rich message: the instant, rendered by <DateTime>.
    const date = (value: string | null | undefined) =>
      function InvitationDate() {
        return <DateTime value={value} />;
      };
    const detail: Record<Invitation["status"], (i: Invitation) => ReactNode> = {
      pending: (i) => t.rich("expires", { date: date(i.expires_at) }),
      accepted: (i) => <DateTime value={i.accepted_at} />,
      revoked: (i) => <DateTime value={i.revoked_at} />,
      expired: (i) => <DateTime value={i.expires_at} />,
    };
    return [
      {
        id: "email",
        kind: "identifier",
        header: t("email"),
        cell: (i) => (
          <div className="min-w-0">
            <span className="font-medium">{i.email}</span>
            <span className="block text-xs text-muted-foreground">
              {i.invited_by
                ? t.rich("sentAtBy", { date: date(i.created_at), email: String(i.invited_by.email ?? "") })
                : t.rich("sentAt", { date: date(i.created_at) })}
            </span>
          </div>
        ),
      },
      {
        id: "status",
        kind: "status",
        header: common("status"),
        cell: (i) => (
          <div>
            <StatusPill status={`users.invitation.${i.status}`} />
            <span className="mt-0.5 block text-xs text-muted-foreground">{detail[i.status](i)}</span>
          </div>
        ),
      },
      { id: "role", kind: "data", header: t("role"), hideBelow: "sm", cell: (i) => i.role.name },
      {
        id: "actions",
        kind: "actions",
        header: <span className="sr-only">{common("actions")}</span>,
        width: "3.5rem",
        cell: (i) =>
          onRevoke && i.status === "pending" ? (
            <IconButton icon={Ban} label={t("revokeLabel", { email: i.email })} disabled={revoking !== undefined} onClick={() => onRevoke(i)} />
          ) : null,
      },
    ];
  }, [t, common, onRevoke, revoking]);
}
