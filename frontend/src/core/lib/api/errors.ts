/**
 * The typed error taxonomy (FRONTEND_PLATFORM.md § 3). Every non-2xx is decoded ONCE, here, into
 * one of a closed set of kinds; components switch on `err.kind` and nothing downstream parses a
 * body. Discriminate on `kind` and `isApiError()` (a brand), never `instanceof`: an error that
 * crosses a bundle boundary (a plugin chunk, a test mock) fails instanceof.
 *
 * The backend envelope is {"error": {"code", "message", "details"?, "request_id"?, ...}}
 * (core/api/errors.py). Structured detail is never stringified into copy: if no message can be
 * derived, the copy is the code map's entry, else "Something went wrong (HTTP <status>)".
 */
import { useEffect, useState } from "react";

import { transport } from "@/core/lib/config/defaults";

export type ErrorKind =
  | "unauthenticated"
  | "reauth_required"
  | "permission"
  | "entitlement"
  | "payment_required"
  | "not_found"
  | "conflict"
  | "validation"
  | "rate_limited"
  | "server"
  | "network";

export type FieldError = { path: string; message: string; code: string };

const BRAND = "__djx_api_error__";

/** Codes the backend uses for "you may not, until you do X" (403 with a remediation). */
const ENTITLEMENT_CODES = new Set(["mfa_enrollment_required", "onboarding_incomplete"]);

export type ApiErrorInit = {
  kind: ErrorKind;
  status: number;
  code: string;
  message?: string;
  method: string;
  path: string;
  requestId?: string;
  body?: unknown;
  details?: unknown;
  fields?: FieldError[];
  nonField?: string[];
  retryAfterSeconds?: number;
  actionKey?: string;
  requiredPermission?: string;
  unmet?: string[];
  remediationUrl?: string;
  timedOut?: boolean;
};

export class ApiError extends Error {
  readonly [BRAND] = true as const;
  readonly kind: ErrorKind;
  readonly status: number;
  readonly code: string;
  /** The server's own message when it sent one; copy is derived by messageFor(). */
  readonly serverMessage: string | undefined;
  readonly method: string;
  readonly path: string;
  readonly requestId: string | undefined;
  readonly body: unknown;
  readonly details: unknown;
  readonly fields: FieldError[];
  readonly nonField: string[];
  readonly retryAfterSeconds: number | undefined;
  readonly actionKey: string | undefined;
  readonly requiredPermission: string | undefined;
  readonly unmet: string[];
  readonly remediationUrl: string | undefined;
  readonly timedOut: boolean;

  constructor(init: ApiErrorInit) {
    super(`API ${init.status} ${init.kind} — ${init.method} ${init.path}`);
    this.name = "ApiError";
    this.kind = init.kind;
    this.status = init.status;
    this.code = init.code;
    this.serverMessage = init.message;
    this.method = init.method;
    this.path = init.path;
    this.requestId = init.requestId;
    this.body = init.body;
    this.details = init.details;
    this.fields = init.fields ?? [];
    this.nonField = init.nonField ?? [];
    this.retryAfterSeconds = init.retryAfterSeconds;
    this.actionKey = init.actionKey;
    this.requiredPermission = init.requiredPermission;
    this.unmet = init.unmet ?? [];
    this.remediationUrl = init.remediationUrl;
    this.timedOut = init.timedOut ?? false;
  }
}

export function isApiError(value: unknown): value is ApiError {
  return (
    typeof value === "object" &&
    value !== null &&
    (value as Record<string, unknown>)[BRAND] === true &&
    typeof (value as Record<string, unknown>).kind === "string"
  );
}

// --- Decoding -------------------------------------------------------------------------------------

type Envelope = {
  code?: unknown;
  message?: unknown;
  details?: unknown;
  request_id?: unknown;
  retry_after_seconds?: unknown;
  action_key?: unknown;
  required_permission?: unknown;
  unmet?: unknown;
  remediation_url?: unknown;
};

function str(value: unknown): string | undefined {
  return typeof value === "string" && value ? value : undefined;
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}

export function kindFor(status: number, code: string | undefined, envelope: Envelope): ErrorKind {
  if (status === 401) return "unauthenticated";
  if (status === 423) return "reauth_required";
  if (status === 402) return "payment_required";
  if (status === 403) {
    const entitled =
      (code !== undefined && ENTITLEMENT_CODES.has(code)) ||
      str(envelope.remediation_url) !== undefined ||
      strings(envelope.unmet).length > 0;
    return entitled ? "entitlement" : "permission";
  }
  if (status === 404) return "not_found";
  if (status === 409 || status === 412) return "conflict";
  if (status === 400) return "validation";
  if (status === 429) return "rate_limited";
  return "server"; // 5xx, and any 4xx the taxonomy does not name (405, 415, …): status is kept
}

/** Flatten DRF-style field errors into {path, message, code}, preserving nested paths exactly. */
export function flattenFields(details: unknown, prefix = ""): FieldError[] {
  if (!details || typeof details !== "object") return [];
  const out: FieldError[] = [];
  const push = (path: string, value: unknown) => {
    if (typeof value === "string") out.push({ path, message: value, code: "invalid" });
    else if (value && typeof value === "object" && "message" in value) {
      const v = value as { message?: unknown; code?: unknown };
      out.push({ path, message: String(v.message ?? ""), code: String(v.code ?? "invalid") });
    }
  };
  for (const [key, value] of Object.entries(details as Record<string, unknown>)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (Array.isArray(value)) {
      for (const [index, item] of value.entries()) {
        if (typeof item === "string" || (item && typeof item === "object" && "message" in item)) {
          push(path, item);
        } else out.push(...flattenFields(item, `${path}.${index}`));
      }
    } else if (value && typeof value === "object") out.push(...flattenFields(value, path));
    else push(path, value);
  }
  return out;
}

/** Retry-After as delta-seconds or an HTTP-date, clamped so a bad header cannot wedge a button. */
export function retryAfterFrom(
  bodySeconds: unknown,
  header: string | null,
  now: number = Date.now(),
): number | undefined {
  let seconds: number | undefined;
  if (typeof bodySeconds === "number" && Number.isFinite(bodySeconds)) seconds = bodySeconds;
  else if (header) {
    const trimmed = header.trim();
    if (/^\d+$/.test(trimmed)) seconds = Number(trimmed);
    else {
      const at = Date.parse(trimmed);
      if (!Number.isNaN(at)) seconds = Math.ceil((at - now) / 1000);
    }
  }
  if (seconds === undefined) return undefined;
  return Math.min(Math.max(0, Math.round(seconds)), transport.maxRetryAfterSeconds);
}

export async function decodeError(res: Response, method: string, path: string): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  const envelope: Envelope =
    body && typeof body === "object" && typeof (body as { error?: unknown }).error === "object"
      ? ((body as { error: Envelope }).error ?? {})
      : {};
  const code = str(envelope.code) ?? `http_${res.status}`;
  const kind = kindFor(res.status, str(envelope.code), envelope);
  const details = envelope.details;
  const nonFieldRaw =
    details && typeof details === "object" && !Array.isArray(details)
      ? (details as Record<string, unknown>).non_field_errors
      : details;
  return new ApiError({
    kind,
    status: res.status,
    code,
    message: str(envelope.message),
    method,
    path,
    requestId: str(envelope.request_id) ?? res.headers.get("X-Request-ID") ?? undefined,
    body,
    details,
    fields: kind === "validation" ? flattenFields(details).filter((f) => f.path !== "non_field_errors") : [],
    nonField: kind === "validation" ? strings(nonFieldRaw) : [],
    retryAfterSeconds:
      kind === "rate_limited"
        ? retryAfterFrom(envelope.retry_after_seconds, res.headers.get("Retry-After"))
        : undefined,
    actionKey: str(envelope.action_key),
    requiredPermission: str(envelope.required_permission),
    unmet: strings(envelope.unmet),
    remediationUrl: str(envelope.remediation_url),
  });
}

export function networkError(method: string, path: string, timedOut: boolean): ApiError {
  return new ApiError({
    kind: "network",
    status: 0,
    code: timedOut ? "timeout" : "network",
    method,
    path,
    timedOut,
  });
}

// --- Copy -----------------------------------------------------------------------------------------

/**
 * Until the backend exports its error catalogue (FRONTEND_PLATFORM § 24), the code → message map
 * is this short local one. The server's own message always wins; an unknown code gets the generic
 * line. Never a stringified detail object.
 */
const MESSAGES: Record<string, string> = {
  invalid: "Some of the information is not valid.",
  not_authenticated: "Please sign in to continue.",
  permission_denied: "You do not have permission to do that.",
  not_found: "That was not found.",
  throttled: "Too many requests. Please wait a moment.",
  mfa_enrollment_required: "Two-factor authentication must be set up before continuing.",
  reauth_required: "Please confirm your password to continue.",
  network: "Could not reach the server. Check your connection.",
  timeout: "The server took too long to answer.",
  server_error: "Something went wrong. Quote the reference if you report it.",
};

export function messageFor(err: ApiError): string {
  if (err.serverMessage) return err.serverMessage;
  const mapped = MESSAGES[err.code];
  if (mapped) return mapped;
  if (process.env.NODE_ENV === "development" && !err.code.startsWith("http_")) {
    console.warn(`[api] no message for error code "${err.code}"`);
  }
  return err.status ? `Something went wrong (HTTP ${err.status}).` : MESSAGES.network;
}

/** The cooldown a rate-limited error asks for; every submit that can be throttled uses it. */
export function useCooldown(err: unknown): { disabled: boolean; secondsLeft: number } {
  const seconds = isApiError(err) && err.kind === "rate_limited" ? (err.retryAfterSeconds ?? 0) : 0;
  const [until, setUntil] = useState(0);
  const [now, setNow] = useState(0);
  // A new error object starts a new cooldown. The clock is read in callbacks, never in render.
  useEffect(() => {
    const start = setTimeout(() => {
      const at = Date.now();
      setNow(at);
      setUntil(seconds > 0 ? at + seconds * 1000 : 0);
    }, 0);
    return () => clearTimeout(start);
  }, [err, seconds]);
  useEffect(() => {
    if (until <= now) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [until, now]);
  const secondsLeft = Math.max(0, Math.ceil((until - now) / 1000));
  return { disabled: secondsLeft > 0, secondsLeft };
}
