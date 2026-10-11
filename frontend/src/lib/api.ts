/**
 * The one transport to the Django backend. Every request goes through here, so the base URL,
 * credentials, CSRF header, refresh-and-retry and error shape live in one place.
 *
 * Auth is httpOnly cookies (ADR-0009): this code never sees a token. It sends cookies
 * (`credentials: "include"`), echoes the readable CSRF cookie on unsafe methods, and on a 401
 * asks the backend once to rotate the session, then retries once.
 */
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Server components reach Django by its container-network address when one is set (Docker:
// `localhost` there is the frontend container). The browser bundle only ever sees API_URL.
const BASE_URL =
  typeof window === "undefined" ? (process.env.INTERNAL_API_URL ?? API_URL) : API_URL;

const COOKIE_PREFIX = process.env.NEXT_PUBLIC_AUTH_COOKIE_PREFIX ?? "dbx";
const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);
// A 401 from these means "not signed in", not "access token expired": never refresh for them.
const NO_REFRESH = new Set(["/api/auth/login/", "/api/auth/refresh/"]);

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly body: unknown,
    path: string,
  ) {
    super(`API ${status} — ${path}`);
    this.name = "ApiError";
  }
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
