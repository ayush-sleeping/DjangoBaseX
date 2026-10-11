/**
 * "Forgot password" and "reset password" (AUTH_BLUEPRINT § 6.6). The pages only call these and
 * show what they return.
 *
 * Forgot always answers 204, whether or not the address has an account: the page must say the same
 * thing either way, or it becomes the user-enumeration oracle the API was built not to be.
 */
import { api, ApiError } from "./api";

export async function requestPasswordReset(email: string): Promise<void> {
  await api<void>("/api/auth/password/forgot/", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

/** On success every session of the account is signed out, this browser's included. */
export async function resetPassword(token: string, password: string): Promise<void> {
  await api<void>("/api/auth/password/reset/", {
    method: "POST",
    body: JSON.stringify({ token, password }),
  });
}

/** The first `token` in the query string, or "" when the link has none. */
export function tokenFromSearchParams(value: string | string[] | undefined): string {
  return (Array.isArray(value) ? value[0] : value)?.trim() ?? "";
}

export function forgotPasswordErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 429) return "Too many reset requests. Wait an hour and try again.";
    if (error.status === 400) return "Enter your email address.";
  }
  return "Could not reach the server. Try again.";
}

export type ResetFailure =
  /** The link cannot be used again: unknown, already used or expired. Ask for a new one. */
  | { kind: "invalid-token"; message: string }
  /** The password was refused; the link still works. One line per validator. */
  | { kind: "invalid-password"; message: string; details: string[] }
  | { kind: "other"; message: string };

type ErrorBody = { error?: { code?: string; message?: string; details?: unknown } } | null;

export function resetFailure(error: unknown): ResetFailure {
  if (error instanceof ApiError) {
    const body = (error.body as ErrorBody)?.error;
    if (error.status === 400 && body?.code === "invalid_token") {
      return {
        kind: "invalid-token",
        message: "This reset link is invalid or has expired. Request a new one.",
      };
    }
    if (error.status === 400 && body?.code === "invalid_password") {
      const details = Array.isArray(body.details)
        ? body.details.filter((d): d is string => typeof d === "string")
        : [];
      return {
        kind: "invalid-password",
        message: body.message ?? "Choose a different password.",
        details,
      };
    }
    if (error.status === 429) {
      return { kind: "other", message: "Too many attempts. Wait a minute and try again." };
    }
  }
  return { kind: "other", message: "Could not reach the server. Try again." };
}
