/**
 * The Content-Security-Policy builder (FRONTEND_PLATFORM § 18, BUILD_ORDER 8.5). Pure: no env, no
 * request, no I/O. src/proxy.ts reads the environment per request and hands the values here.
 *
 * No origin is spelled in this file. Extra origins (storage, error tracker) are DATA, from the
 * runtime variable CSP_EXTRA_ORIGINS, each validated as a bare origin before it reaches a header.
 */

export const CSP_MODES = ["off", "report_only", "enforce"] as const;
export type CspMode = (typeof CSP_MODES)[number];

/** An unknown or unset value is report_only: the safe rollout state, never a crash, never "off". */
export function parseCspMode(raw: string | undefined): CspMode {
  const value = (raw ?? "").trim().toLowerCase();
  return (CSP_MODES as readonly string[]).includes(value) ? (value as CspMode) : "report_only";
}

const ORIGIN_PROTOCOLS = new Set(["http:", "https:", "ws:", "wss:"]);

/** A bare origin (scheme, host, optional port) or null: a path, query, wildcard or space is refused. */
export function parseOrigin(raw: string): string | null {
  const value = raw.trim();
  if (!value || /[\s;,'"*]/.test(value)) return null;
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return null;
  }
  if (!ORIGIN_PROTOCOLS.has(url.protocol) || !url.hostname) return null;
  return url.origin === value.replace(/\/$/, "") ? url.origin : null;
}

/** Comma-separated origins; an invalid entry is dropped (never widens the policy) and reported. */
export function parseExtraOrigins(
  raw: string | undefined,
  onInvalid?: (entry: string) => void,
): string[] {
  const origins: string[] = [];
  for (const entry of (raw ?? "").split(",")) {
    if (!entry.trim()) continue;
    const origin = parseOrigin(entry);
    if (origin === null) onInvalid?.(entry.trim());
    else if (!origins.includes(origin)) origins.push(origin);
  }
  return origins;
}

/** An absolute origin-plus-path URL or a root-relative path; anything else is no report URL. */
export function parseReportUrl(raw: string | undefined): string | undefined {
  const value = (raw ?? "").trim();
  if (!value || /[\s;,'"]/.test(value)) return undefined;
  if (value.startsWith("/") && !value.startsWith("//")) return value;
  try {
    const url = new URL(value);
    return ORIGIN_PROTOCOLS.has(url.protocol) && url.hostname ? url.href : undefined;
  } catch {
    return undefined;
  }
}

type CspInput = {
  nonce: string;
  isDev: boolean;
  /** Validated origins (parseExtraOrigins) allowed for images and connections. */
  extraOrigins?: readonly string[];
  /** Validated (parseReportUrl). */
  reportUrl?: string;
};

/** The report group name shared by `report-to` and the Reporting-Endpoints header. */
export const CSP_REPORT_GROUP = "csp";

export function buildCsp({ nonce, isDev, extraOrigins = [], reportUrl }: CspInput): string {
  if (!/^[A-Za-z0-9+/=]+$/.test(nonce)) throw new Error("CSP nonce must be base64");
  const extra = [...extraOrigins];
  const directives = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${isDev ? " 'unsafe-eval'" : ""}`,
    // No style nonce: a nonce disables 'unsafe-inline' and breaks injected styles (§ 18).
    "style-src 'self' 'unsafe-inline'",
    ["img-src 'self' data: blob:", ...extra].join(" "),
    ["connect-src 'self'", ...extra].join(" "),
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ];
  if (!isDev) directives.push("upgrade-insecure-requests");
  if (reportUrl) directives.push(`report-uri ${reportUrl}`, `report-to ${CSP_REPORT_GROUP}`);
  return directives.join("; ");
}
