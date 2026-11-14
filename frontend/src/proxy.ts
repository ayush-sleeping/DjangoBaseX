/**
 * The page proxy: the navigation guard (FRONTEND_PLATFORM § 8.2, BUILD_ORDER 8.2, TECH_DEBT DB-20)
 * and the per-request Content-Security-Policy (§ 18, BUILD_ORDER 8.5).
 *
 * Guard: decides on the session MARKER cookie, never on a credential: the access cookie is scoped
 * to /api/ and the refresh cookie to the refresh endpoint, so NEITHER is sent on a page navigation.
 * A guard that checked them bounced every signed-in user to sign-in once their 10-minute access
 * token expired, before any JavaScript could refresh it. With the marker:
 *
 * - a public page (per the navigation manifest) → rendered;
 * - marker present → rendered; the client's first API call 401s, refreshes once, and replays;
 * - marker absent  → 307 to /login?next=<the page>, through safeNext().
 *
 * It never reads the access or refresh cookie and never calls the API per request. It is a
 * courtesy, not a control: a forged marker yields an empty shell whose every API call is 401.
 *
 * CSP: a fresh nonce per request. The REQUEST carries `x-nonce` and the policy (Next reads the
 * request header to nonce its own scripts); the RESPONSE carries it as Report-Only or enforcing per
 * CSP_MODE. The environment is read INSIDE the handler, at request time: flipping enforcement is a
 * restart, never a rebuild. A redirect carries no document, so it carries no policy.
 */
import { type NextRequest, NextResponse } from "next/server";

import {
  buildCsp,
  CSP_REPORT_GROUP,
  parseCspMode,
  parseExtraOrigins,
  parseReportUrl,
} from "@/core/lib/security/csp";
import { authCookieNames } from "@/core/lib/session/cookies";
import { safeNext } from "@/core/lib/session/safe-next";
import { MANIFEST_ENTRIES } from "@/core/shell/nav/manifest";
import { resolveRoute } from "@/core/shell/nav/resolve-route";

export const LOGIN_PATH = "/login";

function hasMarker(request: NextRequest): boolean {
  for (const name of authCookieNames("session")) {
    if (request.cookies.get(name)?.value) return true;
  }
  return false;
}

/** A prefetch is not a rendered document: no nonce can be applied to it, and it needs no policy. */
function isPrefetch(request: NextRequest): boolean {
  return request.headers.has("next-router-prefetch") || request.headers.get("purpose") === "prefetch";
}

const warned = new Set<string>();
function warnOnce(entry: string) {
  if (warned.has(entry)) return;
  warned.add(entry);
  console.warn(`CSP_EXTRA_ORIGINS: ignoring "${entry}" (not a bare origin)`);
}

function nextWithCsp(request: NextRequest): NextResponse {
  if (isPrefetch(request)) return NextResponse.next();
  const mode = parseCspMode(process.env.CSP_MODE); // request time, never module load
  const nonce = btoa(crypto.randomUUID());
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  if (mode === "off") return NextResponse.next({ request: { headers: requestHeaders } });

  const reportUrl = parseReportUrl(process.env.CSP_REPORT_URL);
  const policy = buildCsp({
    nonce,
    isDev: process.env.NODE_ENV === "development",
    extraOrigins: parseExtraOrigins(process.env.CSP_EXTRA_ORIGINS, warnOnce),
    reportUrl,
  });
  requestHeaders.set("Content-Security-Policy", policy);
  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set(
    mode === "enforce" ? "Content-Security-Policy" : "Content-Security-Policy-Report-Only",
    policy,
  );
  if (reportUrl) response.headers.set("Reporting-Endpoints", `${CSP_REPORT_GROUP}="${reportUrl}"`);
  return response;
}

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  if (resolveRoute(pathname, MANIFEST_ENTRIES)?.public) return nextWithCsp(request);
  if (hasMarker(request)) return nextWithCsp(request);
  const target = new URL(LOGIN_PATH, request.url);
  target.searchParams.set("next", safeNext(`${pathname}${search}`));
  return NextResponse.redirect(target, 307);
}

export const config = {
  // Pages only: not the API (proxied to Django), not build assets, not files with an extension.
  matcher: ["/((?!api/|_next/static|_next/image|favicon\\.ico|.*\\.[A-Za-z0-9]+$).*)"],
};
