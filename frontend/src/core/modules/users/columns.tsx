/**
 * Columns for the Users and Invitations indexes, in the fixed order (FRONTEND_PLATFORM § 11):
 * identifier → status → data → actions. No sortKey: the users and invitations endpoints accept no
 * `ordering`, and an arrow that does nothing is a lie.
 */
import { Ban, ChevronRight } from "lucide-react";
import Link from "next/link";

import { buttonClass, IconButton } from "@/core/components/Button";
import type { DataTableColumn } from "@/core/components/data-table";
import { StatusPill } from "@/core/components/StatusPill";
import type { Invitation } from "@/core/lib/invitations";
import { formatDateTime, type User } from "@/core/lib/users";

export const userHref = (publicId: string) => `/users/${encodeURIComponent(publicId)}`;
export const userLabel = (user: User) => user.full_name || user.email;

export const USER_COLUMNS: DataTableColumn<User>[] = [
  {
    id: "user",
    kind: "identifier",
    header: "User",
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
    header: "Status",
    cell: (user) => (
      <span className="inline-flex flex-wrap gap-1">
        <StatusPill status={user.is_active ? "user.active" : "user.deactivated"} />
        {user.is_superuser ? <StatusPill status="user.superuser" title="Bypasses every permission check." /> : null}
      </span>
    ),
  },
  {
    id: "roles",
    kind: "data",
    header: "Roles",
    hideBelow: "md",
    cell: (user) => <span className="text-xs">{user.roles.map((role) => role.name).join(", ") || "—"}</span>,
  },
  {
    id: "mfa",
    kind: "data",
    header: "Two-factor",
    hideBelow: "lg",
    cell: (user) => (user.mfa_enabled ? <StatusPill status="user.mfa_on" /> : <span className="text-xs text-muted-foreground">Off</span>),
  },
  {
    id: "last_login",
    kind: "data",
    header: "Last sign-in",
    hideBelow: "sm",
    cell: (user) => <span className="text-xs text-muted-foreground">{formatDateTime(user.last_login)}</span>,
  },
  {
    id: "actions",
    kind: "actions",
    header: <span className="sr-only">Actions</span>,
    width: "3.5rem",
    cell: (user) => (
      <Link href={userHref(user.public_id)} aria-label={`Open ${userLabel(user)}`} title="Open" className={buttonClass("ghost", "sm", "w-8 px-0")}>
        <ChevronRight aria-hidden className="size-4" />
      </Link>
    ),
  },
];

const INVITATION_DETAIL: Record<Invitation["status"], (i: Invitation) => string> = {
  pending: (i) => `Expires ${formatDateTime(i.expires_at)}`,
  accepted: (i) => formatDateTime(i.accepted_at),
  revoked: (i) => formatDateTime(i.revoked_at),
  expired: (i) => formatDateTime(i.expires_at),
};

/** `onRevoke` undefined → no revoke button: a control nobody authorised is never drawn (§ 9). */
export function invitationColumns({ onRevoke, revoking }: { onRevoke?: (i: Invitation) => void; revoking?: string }): DataTableColumn<Invitation>[] {
  return [
    {
      id: "email",
      kind: "identifier",
      header: "Email",
      cell: (i) => (
        <div className="min-w-0">
          <span className="font-medium">{i.email}</span>
          <span className="block text-xs text-muted-foreground">
            Sent {formatDateTime(i.created_at)}
            {i.invited_by ? ` by ${i.invited_by.email}` : ""}
          </span>
        </div>
      ),
    },
    {
      id: "status",
      kind: "status",
      header: "Status",
      cell: (i) => (
        <div>
          <StatusPill status={`invitation.${i.status}`} />
          <span className="mt-0.5 block text-xs text-muted-foreground">{INVITATION_DETAIL[i.status](i)}</span>
        </div>
      ),
    },
    { id: "role", kind: "data", header: "Role", hideBelow: "sm", cell: (i) => i.role.name },
    {
      id: "actions",
      kind: "actions",
      header: <span className="sr-only">Actions</span>,
      width: "3.5rem",
      cell: (i) =>
        onRevoke && i.status === "pending" ? (
          <IconButton icon={Ban} label={`Revoke the invitation to ${i.email}`} disabled={revoking !== undefined} onClick={() => onRevoke(i)} />
        ) : null,
    },
  ];
}
