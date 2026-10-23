/**
 * The one transport to the Django backend. Every request goes through here, so the base URL,
 * credentials, CSRF header, refresh-and-retry and error shape live in one place.
 *
 * Auth is httpOnly cookies (ADR-0009): this code never sees a token. It sends cookies
 * (`credentials: "include"`), echoes the readable CSRF cookie on unsafe methods, and on a 401
 * asks the backend once to rotate the session, then retries once.
 */
import { SHIPPED_COOKIE_PREFIX } from "./identity-defaults";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Server components reach Django by its container-network address when one is set (Docker:
// `localhost` there is the frontend container). The browser bundle only ever sees API_URL.
const BASE_URL =
  typeof window === "undefined" ? (process.env.INTERNAL_API_URL ?? API_URL) : API_URL;

// Must equal the backend's AUTH_COOKIE_PREFIX; setup.sh writes both from the same slug.
const COOKIE_PREFIX = process.env.NEXT_PUBLIC_AUTH_COOKIE_PREFIX || SHIPPED_COOKIE_PREFIX;
const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);
// A 401 from these means "not signed in", not "access token expired": never refresh for them.
// mfa/verify's 401 means the login's mfa_token is spent or expired, and no refresh can fix that.
const NO_REFRESH = new Set(["/api/auth/login/", "/api/auth/refresh/", "/api/auth/mfa/verify/"]);

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly body: unknown,
    path: string,
  ) {
    super(`API ${status} — ${path}`);
    this.name = "ApiError";
  }

  /** The machine-readable `error.code` of the API's error envelope, when there is one. */
  get code(): string | undefined {
    const code = (this.body as { error?: { code?: unknown } } | null)?.error?.code;
    return typeof code === "string" ? code : undefined;
  }

  /** The envelope's `error.details`: field errors, a list of codes, a count. Shape is per code. */
  get details(): unknown {
    return (this.body as { error?: { details?: unknown } } | null)?.error?.details;
  }
}

/** DRF's page envelope, as every paginated list endpoint returns it. */
export type Page<T> = { count: number; next: string | null; previous: string | null; results: T[] };

/** Field → messages, from a 400 `invalid`. Empty when the error is anything else. */
export function fieldErrors(error: unknown): Record<string, string[]> {
  if (!(error instanceof ApiError) || error.status !== 400 || error.code !== "invalid") return {};
  const details = error.details;
  if (!details || typeof details !== "object" || Array.isArray(details)) return {};
  const out: Record<string, string[]> = {};
  for (const [field, messages] of Object.entries(details)) {
    const list = Array.isArray(messages) ? messages : [messages];
    out[field] = list.filter((m): m is string => typeof m === "string");
  }
  return out;
}

/**
 * The user's role requires two-factor and they have not set it up: every endpoint but enrolment,
 * logout and /me answers this. Pages send the user to /account/security (MFA_ENROLMENT_PATH in
 * src/core/lib/mfa.ts); this module never redirects.
 */
export function isMfaEnrollmentRequired(error: unknown): error is ApiError {
  return (
    error instanceof ApiError && error.status === 403 && error.code === "mfa_enrollment_required"
  );
}

/** 423: a sensitive action wants the password confirmed again (re-auth), then one retry. */
export function isReauthRequired(error: unknown): error is ApiError {
  return error instanceof ApiError && error.status === 423 && error.code === "reauth_required";
}

/** The session-bound CSRF value. `__Host-` prefixed when the API sets Secure cookies. */
function readCsrfCookie(): string | undefined {
  const names = new Set([`${COOKIE_PREFIX}_csrf`, `__Host-${COOKIE_PREFIX}_csrf`]);
  for (const part of document.cookie.split("; ")) {
    const separator = part.indexOf("=");
    if (separator > 0 && names.has(part.slice(0, separator))) {
      return decodeURIComponent(part.slice(separator + 1));
    }
  }
  return undefined;
}

function send(path: string, init?: RequestInit): Promise<Response> {
  const headers = new Headers(init?.headers);
  if (!headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const method = (init?.method ?? "GET").toUpperCase();
  if (typeof window !== "undefined" && UNSAFE_METHODS.has(method)) {
    const csrf = readCsrfCookie();
    if (csrf) headers.set("X-CSRF-Token", csrf);
  }
  return fetch(`${BASE_URL}${path}`, { ...init, headers, credentials: "include" });
}

// Single-flight: requests that hit 401 together share one refresh instead of racing it.
let refreshing: Promise<boolean> | null = null;

function refreshSession(): Promise<boolean> {
  refreshing ??= send("/api/auth/refresh/", { method: "POST" })
    .then((res) => res.ok)
    .catch(() => false)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let res = await send(path, init);
  // Only a 401 refreshes. A 403 (not permitted) or 423 (re-auth) is the API's answer for a live
  // session; a refresh would change nothing and burn a rotation.
  if (
    res.status === 401 &&
    typeof window !== "undefined" &&
    !NO_REFRESH.has(path) &&
    (await refreshSession())
  ) {
    res = await send(path, init); // re-reads the CSRF cookie, which the refresh rotated
  }
  if (!res.ok) {
    throw new ApiError(res.status, await res.json().catch(() => null), path);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
