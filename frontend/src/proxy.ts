/**
 * The page-navigation guard (FRONTEND_PLATFORM § 8.2, BUILD_ORDER 8.2, TECH_DEBT DB-20).
 *
 * Decides on the session MARKER cookie, never on a credential: the access cookie is scoped to
 * /api/ and the refresh cookie to the refresh endpoint, so NEITHER is sent on a page navigation.
 * A guard that checked them bounced every signed-in user to sign-in once their 10-minute access
 * token expired, before any JavaScript could refresh it. With the marker:
 *
 * - a public page (per the navigation manifest) → rendered;
 * - marker present → rendered; the client's first API call 401s, refreshes once, and replays;
 * - marker absent  → 307 to /login?next=<the page>, through safeNext().
 *
 * It never reads the access or refresh cookie and never calls the API per request. It is a
 * courtesy, not a control: a forged marker yields an empty shell whose every API call is 401.
 */
import { type NextRequest, NextResponse } from "next/server";

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

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  if (resolveRoute(pathname, MANIFEST_ENTRIES)?.public) return NextResponse.next();
  if (hasMarker(request)) return NextResponse.next();
  const target = new URL(LOGIN_PATH, request.url);
  target.searchParams.set("next", safeNext(`${pathname}${search}`));
  return NextResponse.redirect(target, 307);
}

export const config = {
  // Pages only: not the API (proxied to Django), not build assets, not files with an extension.
  matcher: ["/((?!api/|_next/static|_next/image|favicon\\.ico|.*\\.[A-Za-z0-9]+$).*)"],
};
