/**
 * The Users module (BUILD_ORDER 1.5; AUTH_BLUEPRINT § 10.2). Pages call these and the message
 * helpers; they never shape a request or read an error body themselves.
 */
import type { components } from "@/generated/api";

import { api, ApiError, type Page } from "./api";

/** The code each endpoint enforces. Gate every control on exactly one of these (affordance parity). */
export const USER_CODES = {
  /** GET the list and a user. */
  view: "users.users.view",
  /** POST /api/users/. */
  create: "users.users.create",
  /** PATCH a user (full_name). */
  update: "users.users.update",
  /** POST deactivate AND activate: one right for both directions. */
  deactivate: "users.users.deactivate",
  /** POST a user's sessions/revoke/. */
  revokeSessions: "users.sessions.revoke",
} as const;

/** A role as embedded in other records: the API's RoleSummary (generated, DB-4). */
export type RoleRef = components["schemas"]["RoleSummary"];

/** The API's User (generated from the OpenAPI contract, DB-4). No is_staff, on purpose (§ 3.1). */
export type User = components["schemas"]["User"];

const USERS = "/api/users/";
const userUrl = (publicId: string) => `${USERS}${encodeURIComponent(publicId)}/`;

export async function listUsers(page = 1, search = "", signal?: AbortSignal): Promise<Page<User>> {
  const query = new URLSearchParams({ page: String(page) });
  if (search.trim()) query.set("search", search.trim());
  return api<Page<User>>(`${USERS}?${query}`, { cache: "no-store", signal });
}

export async function getUser(publicId: string, signal?: AbortSignal): Promise<User> {
  return api<User>(userUrl(publicId), { cache: "no-store", signal });
}

/** The account starts active with no usable password; the API emails a set-your-password link. */
export async function createUser(email: string, fullName: string): Promise<User> {
  return api<User>(USERS, {
    method: "POST",
    body: JSON.stringify({ email, full_name: fullName }),
  });
}

export async function updateUser(publicId: string, fullName: string): Promise<User> {
  return api<User>(userUrl(publicId), {
    method: "PATCH",
    body: JSON.stringify({ full_name: fullName }),
  });
}

/** Also signs the user out everywhere: the API revokes every session. */
export async function deactivateUser(publicId: string, reason: string): Promise<User> {
  return api<User>(`${userUrl(publicId)}deactivate/`, {
    method: "POST",
    body: JSON.stringify(reason.trim() ? { reason: reason.trim() } : {}),
  });
}

export async function activateUser(publicId: string): Promise<User> {
  return api<User>(`${userUrl(publicId)}activate/`, { method: "POST", body: "{}" });
}

/** Returns how many sessions were signed out. */
export async function revokeUserSessions(publicId: string): Promise<number> {
  const body = await api<{ revoked: number }>(`${userUrl(publicId)}sessions/revoke/`, {
    method: "POST",
    body: "{}",
  });
  return body.revoked;
}

export function usersErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return "Could not reach the server. Try again.";
  switch (error.code) {
    case "self_deactivation":
      return "You cannot deactivate your own account.";
    case "last_superuser":
      return "This is the last active superuser. Make someone else a superuser first.";
    case "invalid":
      return "Check the highlighted fields.";
    case "mfa_enrollment_required":
      return "Your role requires two-factor authentication. Set it up first.";
  }
  // DRF's own denials carry only {"detail": "..."}; the status says enough.
  if (error.status === 403) return "You don't have permission to do that.";
  if (error.status === 404) return "That user does not exist, or you cannot see them.";
  if (error.status === 401) return "Your session has ended. Sign in again.";
  if (error.status === 429) return "Too many requests. Wait a minute and try again.";
  return "Something went wrong. Try again.";
}
