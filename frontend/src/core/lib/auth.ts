/**
 * Sign-in, sign-out and "who am I" for client components (ADR-0009).
 *
 * Authenticated data is fetched CLIENT-side: the session is an httpOnly cookie, and a server
 * component's own fetch() does not carry the browser's cookies, so it would silently get the
 * signed-out answer (NEXTJS_STANDARDS.md § 3).
 */
import { api, ApiError } from "./api";

export type Me = {
  public_id: string;
  email: string;
  full_name: string;
  is_staff: boolean;
  is_superuser: boolean;
  permissions: string[];
  /** A confirmed two-factor device exists. */
  mfa_enabled: boolean;
  /** The user's role requires two-factor (AUTH_BLUEPRINT § 6.8). */
  mfa_enforced: boolean;
};

/** The signed-in user, or null when there is no live session. */
export async function fetchMe(): Promise<Me | null> {
  try {
    return await api<Me>("/api/auth/me/", { cache: "no-store" });
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null;
    throw error;
  }
}

/**
 * The password step. With two-factor on, the API sets no cookies yet: it answers 200 with a
 * short-lived `mfa_token` that buys exactly one call, to completeMfaSignIn().
 */
export type SignInResult = { status: "signed-in" } | { status: "mfa-required"; mfaToken: string };

export async function signIn(email: string, password: string): Promise<SignInResult> {
  const body = await api<{ mfa_required?: boolean; mfa_token?: string } | undefined>(
    "/api/auth/login/",
    { method: "POST", body: JSON.stringify({ email, password }) },
  );
  if (body?.mfa_required && body.mfa_token) {
    return { status: "mfa-required", mfaToken: body.mfa_token };
  }
  return { status: "signed-in" };
}

/** The code step: a 6-digit authenticator code or a recovery code. Sets the session cookies. */
export async function completeMfaSignIn(mfaToken: string, code: string): Promise<void> {
  await api<void>("/api/auth/mfa/verify/", {
    method: "POST",
    body: JSON.stringify({ mfa_token: mfaToken, code }),
  });
}

export async function signOut(): Promise<void> {
  await api<void>("/api/auth/logout/", { method: "POST" });
}

/** Re-authentication (AUTH_BLUEPRINT § 6.9): confirms the password for THIS session only. */
export async function confirmPassword(password: string): Promise<void> {
  await api<void>("/api/auth/password/confirm/", {
    method: "POST",
    body: JSON.stringify({ password }),
  });
}

/** A message safe to show for a failed sign-in. The API gives one answer for every bad login. */
export function signInErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const body = error.body as { error?: { message?: string } } | null;
    if (error.status === 401) return body?.error?.message ?? "Email or password is incorrect.";
    if (error.status === 429) return "Too many attempts. Wait a minute and try again.";
    if (error.status === 400) return "Enter your email and password.";
  }
  return "Could not reach the server. Try again.";
}

/**
 * What a failed code step means for the form: retry the code, or start again from the password
 * (the mfa_token expired after 5 minutes or was already used).
 */
export type MfaStepFailure = { restart: boolean; message: string };

export function mfaStepFailure(error: unknown): MfaStepFailure {
  if (error instanceof ApiError) {
    if (error.status === 401 && error.code === "mfa_token_invalid") {
      return { restart: true, message: "That sign-in took too long. Enter your password again." };
    }
    if (error.status === 400) {
      return { restart: false, message: "That code is not valid. Check it and try again." };
    }
    if (error.status === 429) {
      return { restart: false, message: "Too many attempts. Wait a minute and try again." };
    }
  }
  return { restart: false, message: "Could not reach the server. Try again." };
}
