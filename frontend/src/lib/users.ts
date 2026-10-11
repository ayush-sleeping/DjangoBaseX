/**
 * The Users module (BUILD_ORDER 1.5; AUTH_BLUEPRINT § 10.2). Pages call these and the message
 * helpers; they never shape a request or read an error body themselves.
 */
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

export type RoleRef = { public_id: string; slug: string; name: string };

/** No is_staff, on purpose: it is Django-admin trust, not an authorization concept (§ 3.1). */
export type User = {
  public_id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  is_superuser: boolean;
  mfa_enabled: boolean;
  last_login: string | null;
  created_at: string;
  deactivated_at: string | null;
  deactivated_reason: string;
  roles: RoleRef[];
};

const USERS = "/api/users/";
const userUrl = (publicId: string) => `${USERS}${encodeURIComponent(publicId)}/`;

export async function listUsers(page = 1, search = ""): Promise<Page<User>> {
  const query = new URLSearchParams({ page: String(page) });
  if (search.trim()) query.set("search", search.trim());
  return api<Page<User>>(`${USERS}?${query}`, { cache: "no-store" });
}

export async function getUser(publicId: string): Promise<User> {
  return api<User>(userUrl(publicId), { cache: "no-store" });
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

/** The URL of the users list, for history.replaceState: shareable, and Back works. */
export function usersListHref(page: number, search: string): string {
  const query = new URLSearchParams();
  if (page > 1) query.set("page", String(page));
  if (search.trim()) query.set("search", search.trim());
  const qs = query.toString();
  return qs ? `/users?${qs}` : "/users";
}

/** A positive integer from a query-string value, or 1. */
export function pageFromSearchParams(value: string | string[] | undefined): number {
  const raw = Array.isArray(value) ? value[0] : value;
  const page = Number.parseInt(raw ?? "", 10);
  return Number.isFinite(page) && page > 0 ? page : 1;
}

/** "11 Oct 2026, 20:41" in the viewer's locale and time zone; "—" for null. */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
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
