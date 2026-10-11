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

export async function signIn(email: string, password: string): Promise<void> {
  await api<void>("/api/auth/login/", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export async function signOut(): Promise<void> {
  await api<void>("/api/auth/logout/", { method: "POST" });
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
