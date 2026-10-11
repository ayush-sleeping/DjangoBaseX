/**
 * Invitations: the way a person who is not yet a user becomes one (AUTH_BLUEPRINT § 3.5, § 10.1).
 *
 * The accept step is public and authenticates by the token in the emailed link, like a password
 * reset: the page carrying it follows the token-page rule (NEXTJS_STANDARDS § 3).
 */
import { api, ApiError, type Page } from "./api";
import type { RoleRef } from "./users";

/** List, send and revoke are one right: whoever may invite may see and withdraw invitations. */
export const INVITATION_CODES = {
  send: "users.invitations.send",
} as const;

export type InvitationStatus = "pending" | "accepted" | "revoked" | "expired";

export type Invitation = {
  public_id: string;
  email: string;
  role: RoleRef;
  invited_by: { public_id: string; email: string } | null;
  status: InvitationStatus;
  expires_at: string;
  accepted_at: string | null;
  revoked_at: string | null;
  created_at: string;
};

const INVITATIONS = "/api/users/invitations/";

export async function listInvitations(page = 1): Promise<Page<Invitation>> {
  return api<Page<Invitation>>(`${INVITATIONS}?page=${page}`, { cache: "no-store" });
}

export async function sendInvitation(email: string, rolePublicId: string): Promise<Invitation> {
  return api<Invitation>(INVITATIONS, {
    method: "POST",
    body: JSON.stringify({ email, role: rolePublicId }),
  });
}

export async function revokeInvitation(publicId: string): Promise<Invitation> {
  return api<Invitation>(`${INVITATIONS}${encodeURIComponent(publicId)}/revoke/`, {
    method: "POST",
    body: "{}",
  });
}

/** Public. On success the API sets the session cookies: the new user is signed in. */
export async function acceptInvitation(
  token: string,
  password: string,
  fullName: string,
): Promise<void> {
  await api<void>("/api/auth/invitations/accept/", {
    method: "POST",
    body: JSON.stringify({ token, password, full_name: fullName }),
  });
}

export const STATUS_LABELS: Record<InvitationStatus, string> = {
  pending: "Pending",
  accepted: "Accepted",
  revoked: "Revoked",
  expired: "Expired",
};

export function invitationErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return "Could not reach the server. Try again.";
  switch (error.code) {
    case "already_invited":
      return "That address already has a pending invitation. Revoke it to send a new one.";
    case "already_a_user":
      return "That address already belongs to a user.";
    case "elevated_requires_superuser":
      return "Only a superuser can invite someone into an elevated role.";
    case "not_pending":
      return "That invitation is no longer pending, so there is nothing to revoke.";
    case "invalid":
      return "Check the highlighted fields.";
    case "mfa_enrollment_required":
      return "Your role requires two-factor authentication. Set it up first.";
  }
  if (error.status === 403) return "You don't have permission to do that.";
  if (error.status === 404) return "That invitation does not exist, or you cannot see it.";
  if (error.status === 401) return "Your session has ended. Sign in again.";
  if (error.status === 429) return "Too many requests. Wait a minute and try again.";
  return "Something went wrong. Try again.";
}

export type AcceptFailure =
  /** Unknown, used, revoked or expired: the link cannot work again. Ask for a new invitation. */
  | { kind: "invalid-token"; message: string }
  /** The password was refused; the link still works. One line per validator. */
  | { kind: "invalid-password"; message: string; details: string[] }
  | { kind: "other"; message: string };

export function acceptFailure(error: unknown): AcceptFailure {
  if (error instanceof ApiError && error.status === 400) {
    if (error.code === "invalid_token") {
      return {
        kind: "invalid-token",
        message:
          "This invitation link is invalid, has expired, or was already used. Ask whoever " +
          "invited you to send a new one.",
      };
    }
    if (error.code === "invalid_password") {
      const details = Array.isArray(error.details)
        ? error.details.filter((d): d is string => typeof d === "string")
        : [];
      return { kind: "invalid-password", message: "Choose a different password.", details };
    }
    return { kind: "other", message: "Enter your name and a password." };
  }
  if (error instanceof ApiError && error.status === 429) {
    return { kind: "other", message: "Too many attempts. Wait a minute and try again." };
  }
  return { kind: "other", message: "Could not reach the server. Try again." };
}
