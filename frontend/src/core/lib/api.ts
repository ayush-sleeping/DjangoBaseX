/**
 * The API boundary every page imports (NEXTJS_STANDARDS § 2). Since BUILD_ORDER 8.1 the transport
 * itself is src/core/lib/api/client.ts and the error taxonomy src/core/lib/api/errors.ts; this
 * module keeps the names existing callers use and adds nothing of its own.
 */
import { request, type RequestOpts } from "./api/client";
import { ApiError, isApiError } from "./api/errors";

export { API_URL, download, request, upload } from "./api/client";
export { ApiError, isApiError, messageFor } from "./api/errors";
export { useCooldown } from "./api/cooldown";
export type { ErrorKind, FieldError } from "./api/errors";

/** DRF's page envelope, as every paginated list endpoint returns it. */
export type Page<T> = { count: number; next: string | null; previous: string | null; results: T[] };

/** The one call shape pages used before 8.1: a RequestInit whose body is already a JSON string. */
export function api<T>(path: string, init?: RequestInit): Promise<T> {
  const { headers, body, method, signal, ...rest } = init ?? {};
  const opts: RequestOpts = {
    ...(rest as Omit<RequestOpts, "body" | "headers" | "method" | "signal">),
    method: method ?? "GET",
    body: body === null ? undefined : (body as unknown),
    headers: headers ? Object.fromEntries(new Headers(headers).entries()) : undefined,
    signal: signal ?? undefined,
  };
  return request<T>(path, opts);
}

/** Field → messages, from a 400 `invalid`. Empty when the error is anything else. */
export function fieldErrors(error: unknown): Record<string, string[]> {
  if (!isApiError(error) || error.kind !== "validation") return {};
  const out: Record<string, string[]> = {};
  for (const field of error.fields) (out[field.path] ??= []).push(field.message);
  return out;
}

/**
 * The user's role requires two-factor and they have not set it up: every endpoint but enrolment,
 * logout and /me answers this. Pages send the user to /account/security (MFA_ENROLMENT_PATH in
 * src/core/lib/mfa.ts); this module never redirects.
 */
export function isMfaEnrollmentRequired(error: unknown): error is ApiError {
  return isApiError(error) && error.status === 403 && error.code === "mfa_enrollment_required";
}

/** 423: a sensitive action wants the password confirmed again (re-auth), then one retry. */
export function isReauthRequired(error: unknown): error is ApiError {
  return isApiError(error) && error.kind === "reauth_required";
}
