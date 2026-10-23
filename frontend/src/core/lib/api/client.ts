/**
 * The one transport (FRONTEND_PLATFORM.md § 2). Every backend call goes through here, so the base
 * URL, credentials, every header, timeouts, the single-flight refresh and error decoding live in
 * one place. ESLint refuses `fetch` anywhere else.
 *
 * Auth is httpOnly cookies (ADR-0009): this code never sees a token. `credentials: "include"` on
 * every call; the readable CSRF cookie is echoed on unsafe methods; a 401 asks the backend once
 * to rotate the session (one refresh shared by every concurrent 401) and replays each waiting
 * request once. The refresh, logout and login calls bypass that interceptor.
 *
 * As built: the browser base is NEXT_PUBLIC_API_URL (the dev topology serves the API on another
 * origin), not the relative "/api" § 2 prefers for same-origin deployments; server components use
 * INTERNAL_API_URL. Both come from env (NEXTJS_STANDARDS § 2).
 */
import { SHIPPED_COOKIE_PREFIX } from "@/core/lib/identity-defaults";
import { transport } from "@/core/lib/config/defaults";

import { ApiError, decodeError, networkError } from "./errors";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const BASE_URL =
  typeof window === "undefined" ? (process.env.INTERNAL_API_URL ?? API_URL) : API_URL;

const COOKIE_PREFIX = process.env.NEXT_PUBLIC_AUTH_COOKIE_PREFIX || SHIPPED_COOKIE_PREFIX;
const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);
/** A 401 from these means "not signed in", not "access token expired": never refresh for them. */
const NO_REFRESH = new Set(["/api/auth/login/", "/api/auth/refresh/", "/api/auth/mfa/verify/"]);

export type RequestOpts = Omit<RequestInit, "body" | "headers" | "method" | "signal"> & {
  method?: string;
  /** A JSON-able value, a pre-serialised string, or FormData (upload). */
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  /** Do not refresh-and-retry on 401 (the refresh and logout calls themselves). */
  noAuthRetry?: boolean;
  /** Unbounded reads: exports, reports. */
  longTimeout?: boolean;
  timeoutMs?: number;
  idempotencyKey?: string;
};

// --- Headers: the only place they are assembled ------------------------------------------------

export type HeaderContributor = (ctx: { method: string; path: string }) => Record<string, string>;
const contributors = new Set<HeaderContributor>();

/** A module (tenancy, locale) adds its header here; core names no tenant concept itself. */
export function registerHeaderContributor(fn: HeaderContributor): () => void {
  contributors.add(fn);
  return () => contributors.delete(fn);
}

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

function newRequestId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID().replace(/-/g, "")
    : Math.random().toString(36).slice(2);
}

export function buildHeaders(method: string, path: string, opts: RequestOpts): Headers {
  const headers = new Headers(opts.headers);
  if (!headers.has("Accept")) headers.set("Accept", "application/json");
  const isForm = typeof FormData !== "undefined" && opts.body instanceof FormData;
  if (opts.body !== undefined && !isForm && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (typeof window !== "undefined") {
    if (UNSAFE_METHODS.has(method)) {
      const csrf = readCsrfCookie();
      if (csrf) headers.set("X-CSRF-Token", csrf);
    }
    const lang = document.documentElement.lang;
    if (lang && !headers.has("Accept-Language")) headers.set("Accept-Language", lang);
  }
  if (!headers.has("X-Request-ID")) headers.set("X-Request-ID", newRequestId());
  if (opts.idempotencyKey) headers.set("Idempotency-Key", opts.idempotencyKey);
  for (const contribute of contributors) {
    for (const [name, value] of Object.entries(contribute({ method, path }))) headers.set(name, value);
  }
  return headers;
}

// --- Response metadata the error surfaces and the bootstrap query read -------------------------

const meta: { requestId?: string; permissionsVersion?: string } = {};

export function lastResponseMeta(): Readonly<typeof meta> {
  return meta;
}

function record(res: Response): void {
  meta.requestId = res.headers.get("X-Request-ID") ?? meta.requestId;
  meta.permissionsVersion = res.headers.get("X-Permissions-Version") ?? meta.permissionsVersion;
}

// --- Sending ---------------------------------------------------------------------------------------

function serialise(body: unknown): BodyInit | undefined {
  if (body === undefined) return undefined;
  if (typeof body === "string") return body;
  if (typeof FormData !== "undefined" && body instanceof FormData) return body;
  return JSON.stringify(body);
}

async function send(path: string, opts: RequestOpts): Promise<Response> {
  const method = (opts.method ?? "GET").toUpperCase();
  const { body, signal, longTimeout, timeoutMs, ...rest } = opts;
  // headers, noAuthRetry and idempotencyKey are consumed by buildHeaders / sendWithRetry, not fetch.
  const { headers: _headers, noAuthRetry: _retry, idempotencyKey: _key, ...init } = rest;
  void _headers;
  void _retry;
  void _key;
  const budget = timeoutMs ?? (longTimeout ? transport.longTimeoutMs : transport.timeoutMs);
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, budget);
  const onAbort = () => controller.abort();
  signal?.addEventListener("abort", onAbort, { once: true });
  try {
    const res = await fetch(`${BASE_URL}${path}`, {
      ...init,
      method,
      headers: buildHeaders(method, path, opts),
      body: serialise(body),
      credentials: "include",
      signal: controller.signal,
    });
    record(res);
    return res;
  } catch (error) {
    if (signal?.aborted && !timedOut) throw error; // the caller cancelled: let it see its own abort
    throw networkError(method, path, timedOut);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onAbort);
  }
}

// Single-flight: requests that hit 401 together share one refresh instead of racing it.
let refreshing: Promise<boolean> | null = null;

function refreshOnce(): Promise<boolean> {
  refreshing ??= send("/api/auth/refresh/", { method: "POST", noAuthRetry: true })
    .then((res) => res.ok)
    .catch(() => false)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

async function sendWithRetry(path: string, opts: RequestOpts): Promise<Response> {
  let res = await send(path, opts);
  if (
    res.status === 401 &&
    typeof window !== "undefined" &&
    !opts.noAuthRetry &&
    !NO_REFRESH.has(path) &&
    (await refreshOnce())
  ) {
    res = await send(path, opts); // replayed once; re-reads the CSRF cookie the refresh rotated
  }
  return res;
}

// --- Entry points ------------------------------------------------------------------------------------

/** JSON in, JSON out. A non-2xx becomes an ApiError (the only decoder); 204 resolves undefined. */
export async function request<T>(path: string, opts: RequestOpts = {}): Promise<T> {
  const res = await sendWithRetry(path, opts);
  if (!res.ok) throw await decodeError(res, (opts.method ?? "GET").toUpperCase(), path);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** Multipart: the browser writes the boundary, so no Content-Type is set here. */
export function upload<T>(path: string, form: FormData, opts: RequestOpts = {}): Promise<T> {
  return request<T>(path, { ...opts, method: opts.method ?? "POST", body: form });
}

export type Download =
  | { kind: "file"; blob: Blob; filename: string | undefined }
  | { kind: "job"; job: unknown };

/** A file, or the job descriptor when the server answers 202 ("an export job was queued"). */
export async function download(path: string, opts: RequestOpts = {}): Promise<Download> {
  const res = await sendWithRetry(path, { longTimeout: true, ...opts });
  if (!res.ok) throw await decodeError(res, (opts.method ?? "GET").toUpperCase(), path);
  if (res.status === 202) return { kind: "job", job: await res.json().catch(() => null) };
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition);
  return { kind: "file", blob: await res.blob(), filename: match ? decodeURIComponent(match[1]) : undefined };
}

/** For the rare endpoint that reports totals in X-Total-Count rather than the list envelope. */
export async function requestWithTotal<T>(
  path: string,
  opts: RequestOpts = {},
): Promise<{ data: T; total: number | undefined }> {
  const res = await sendWithRetry(path, opts);
  if (!res.ok) throw await decodeError(res, (opts.method ?? "GET").toUpperCase(), path);
  const header = res.headers.get("X-Total-Count");
  const total = header === null ? undefined : Number(header);
  return { data: (await res.json()) as T, total: Number.isFinite(total) ? total : undefined };
}

export const get = <T>(path: string, opts?: RequestOpts) => request<T>(path, { ...opts, method: "GET" });
export const post = <T>(path: string, body?: unknown, opts?: RequestOpts) =>
  request<T>(path, { ...opts, method: "POST", body });
export const patch = <T>(path: string, body?: unknown, opts?: RequestOpts) =>
  request<T>(path, { ...opts, method: "PATCH", body });
export const del = <T = undefined>(path: string, opts?: RequestOpts) =>
  request<T>(path, { ...opts, method: "DELETE" });

export { ApiError };
