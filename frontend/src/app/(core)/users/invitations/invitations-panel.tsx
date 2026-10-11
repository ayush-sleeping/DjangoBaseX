"use client";

// Client component: invitations are authenticated data, and the session is an httpOnly cookie.
import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";

import { fieldErrors, isMfaEnrollmentRequired, type Page } from "@/core/lib/api";
import {
  type Invitation,
  INVITATION_CODES,
  invitationErrorMessage,
  listInvitations,
  revokeInvitation,
  sendInvitation,
  STATUS_LABELS,
} from "@/core/lib/invitations";
import { MFA_ENROLMENT_PATH } from "@/core/lib/mfa";
import { isSuperuser, usePermissions } from "@/core/lib/permissions";
import { assignableBy, listAllRoles, type Role, ROLE_CODES, rbacErrorMessage } from "@/core/lib/rbac";
import { formatDateTime } from "@/core/lib/users";

import { Gate, ui } from "../gate";

type Listing = { page: number; version: number; invitations?: Page<Invitation>; error?: string };

export function InvitationsPanel() {
  const router = useRouter();
  const perms = usePermissions();
  const allowed = perms.can(INVITATION_CODES.send);
  const [page, setPage] = useState(1);
  // Bumped after a send or a revoke, so the list reloads without changing page.
  const [version, setVersion] = useState(0);
  const [listing, setListing] = useState<Listing | null>(null);
  const [rowError, setRowError] = useState<string>();
  const [revoking, setRevoking] = useState<string>();

  useEffect(() => {
    if (!allowed) return;
    let active = true;
    listInvitations(page)
      .then((invitations) => {
        if (active) setListing({ page, version, invitations });
      })
      .catch((error) => {
        if (!active) return;
        if (isMfaEnrollmentRequired(error)) router.push(MFA_ENROLMENT_PATH);
        setListing({ page, version, error: invitationErrorMessage(error) });
      });
    return () => {
      active = false;
    };
  }, [allowed, page, version, router]);

  async function handleRevoke(invitation: Invitation) {
    setRevoking(invitation.public_id);
    setRowError(undefined);
    try {
      await revokeInvitation(invitation.public_id);
      setVersion((v) => v + 1);
    } catch (error) {
      setRowError(invitationErrorMessage(error));
    } finally {
      setRevoking(undefined);
    }
  }

  return (
    <Gate perms={perms} code={INVITATION_CODES.send} what="invite people">
      {() => {
        const loading = !listing || listing.page !== page || listing.version !== version;
        const invitations = listing?.invitations;
        return (
          <div className="flex w-full flex-col items-center gap-6">
            <SendForm
              canListRoles={perms.can(ROLE_CODES.view)}
              superuser={isSuperuser(perms.me)}
              onSent={() => {
                setPage(1);
                setVersion((v) => v + 1);
              }}
            />
            <section className={ui.card}>
              <h2 className="text-sm font-semibold">Sent</h2>
              {loading && !invitations ? (
                <p className="text-sm text-zinc-500">Loading invitations…</p>
              ) : listing?.error ? (
                <p role="alert" className={ui.error}>
                  {listing.error}
                </p>
              ) : invitations && invitations.results.length > 0 ? (
                <table className="w-full text-left text-sm">
                  <thead className="text-xs uppercase tracking-wide text-zinc-500">
                    <tr>
                      <th className="pb-2 font-medium">Email</th>
                      <th className="pb-2 font-medium">Role</th>
                      <th className="pb-2 font-medium">Status</th>
                      <th className="pb-2" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                    {invitations.results.map((invitation) => (
                      <tr key={invitation.public_id}>
                        <td className="py-2 pr-3">
                          {invitation.email}
                          <span className="block text-xs text-zinc-500">
                            Sent {formatDateTime(invitation.created_at)}
                            {invitation.invited_by ? ` by ${invitation.invited_by.email}` : ""}
                          </span>
                        </td>
                        <td className="py-2 pr-3">{invitation.role.name}</td>
                        <td className="py-2 pr-3 text-xs">
                          {STATUS_LABELS[invitation.status]}
                          <span className="block text-zinc-500">{statusDetail(invitation)}</span>
                        </td>
                        <td className="py-2 text-right">
                          {invitation.status === "pending" ? (
                            <button
                              type="button"
                              className={ui.quiet}
                              disabled={revoking !== undefined}
                              onClick={() => handleRevoke(invitation)}
                            >
                              {revoking === invitation.public_id ? "Revoking…" : "Revoke"}
                            </button>
                          ) : null}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="text-sm text-zinc-500">No invitations yet.</p>
              )}
              {rowError ? (
                <p role="alert" className={ui.error}>
                  {rowError}
                </p>
              ) : null}
              {invitations && (invitations.previous || invitations.next) ? (
                <nav className="flex items-center justify-between text-sm">
                  <button
                    type="button"
                    className="underline disabled:no-underline disabled:opacity-40"
                    disabled={!invitations.previous || loading}
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                  >
                    Previous
                  </button>
                  <span className="text-zinc-500">
                    Page {page} · {invitations.count} invitations
                  </span>
                  <button
                    type="button"
                    className="underline disabled:no-underline disabled:opacity-40"
                    disabled={!invitations.next || loading}
                    onClick={() => setPage((p) => p + 1)}
                  >
                    Next
                  </button>
                </nav>
              ) : null}
            </section>
          </div>
        );
      }}
    </Gate>
  );
}

function statusDetail(invitation: Invitation): string {
  switch (invitation.status) {
    case "pending":
      return `Expires ${formatDateTime(invitation.expires_at)}`;
    case "accepted":
      return formatDateTime(invitation.accepted_at);
    case "revoked":
      return formatDateTime(invitation.revoked_at);
    case "expired":
      return formatDateTime(invitation.expires_at);
  }
}

function SendForm({
  canListRoles,
  superuser,
  onSent,
}: {
  /** The role picker reads GET /api/rbac/roles/, which needs rbac.roles.view. */
  canListRoles: boolean;
  superuser: boolean;
  onSent: () => void;
}) {
  const [roles, setRoles] = useState<Role[] | null>(null);
  const [rolesError, setRolesError] = useState<string>();
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string }>();
  const [fields, setFields] = useState<Record<string, string[]>>({});

  useEffect(() => {
    if (!canListRoles) return;
    let active = true;
    listAllRoles()
      .then((all) => {
        // An elevated role can only be handed out by a superuser (§ 8.2): don't offer it.
        if (active) setRoles(all.filter((role) => assignableBy(role, superuser)));
      })
      .catch((error) => {
        if (active) setRolesError(rbacErrorMessage(error));
      });
    return () => {
      active = false;
    };
  }, [canListRoles, superuser]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const email = String(form.get("email") ?? "");
    setPending(true);
    try {
      await sendInvitation(email, String(form.get("role") ?? ""));
      setMessage({ ok: true, text: `Invitation sent to ${email}.` });
      setFields({});
      formElement.reset();
      onSent();
    } catch (error) {
      setMessage({ ok: false, text: invitationErrorMessage(error) });
      setFields(fieldErrors(error));
    } finally {
      setPending(false);
    }
  }

  if (!canListRoles) {
    return (
      <section className={ui.card}>
        <p className="text-sm text-zinc-500">
          Sending an invitation means choosing a role, and you can&apos;t view roles. Ask someone
          who can.
        </p>
      </section>
    );
  }

  const fieldError = (field: string) =>
    fields[field]?.length ? (
      <span className="mt-1 block text-xs text-red-600">{fields[field].join(" ")}</span>
    ) : null;

  return (
    <form onSubmit={handleSubmit} className={ui.card} noValidate>
      <h2 className="text-sm font-semibold">Invite someone</h2>
      <p className="text-xs text-zinc-500">
        They get an email with a link to choose their name and password. They hold the role from
        the moment they accept.
      </p>
      <label className="block text-sm">
        Email
        <input name="email" type="email" required autoComplete="off" className={ui.input} />
        {fieldError("email")}
      </label>
      <label className="block text-sm">
        Role
        {roles === null ? (
          <span className="mt-1 block text-xs text-zinc-500">
            {rolesError ?? "Loading roles…"}
          </span>
        ) : (
          <select name="role" required className={ui.input} defaultValue="">
            <option value="" disabled>
              Choose a role
            </option>
            {roles.map((role) => (
              <option key={role.public_id} value={role.public_id}>
                {role.name}
                {role.is_elevated ? " (elevated)" : ""}
              </option>
            ))}
          </select>
        )}
        {fieldError("role")}
      </label>
      {message ? (
        <p role={message.ok ? "status" : "alert"} className={message.ok ? "text-sm" : ui.error}>
          {message.text}
        </p>
      ) : null}
      <button type="submit" disabled={pending || roles === null} className={ui.button}>
        {pending ? "Sending…" : "Send invitation"}
      </button>
    </form>
  );
}
