/**
 * The marker regression test (FRONTEND_PLATFORM § 8.2, BUILD_ORDER 8.2 acceptance (b), first
 * half): a signed-in user whose access token has expired navigates to a page. The browser sends
 * only the Path=/ marker — the /api/-scoped access cookie and the refresh-scoped refresh cookie are
 * not sent on a page request — and the proxy must let the page render, not bounce to sign-in.
 */
// The installed Next exports unstable_doesMiddlewareMatch; its proxy.md names it unstable_doesProxyMatch.
import { getRedirectUrl, unstable_doesMiddlewareMatch } from "next/experimental/testing/server";
import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

import { AUTH_COOKIE_PREFIX } from "@/core/lib/session/cookies";

import { config, proxy } from "./proxy";

const ORIGIN = "https://app.example.test";

function page(path: string, cookies: Record<string, string> = {}): NextRequest {
  const cookie = Object.entries(cookies)
    .map(([k, v]) => `${k}=${v}`)
    .join("; ");
  return new NextRequest(`${ORIGIN}${path}`, { headers: cookie ? { cookie } : {} });
}

const passed = (res: Response) => res.headers.get("x-middleware-next") === "1";

describe("proxy: the session marker, not a credential, decides page navigations", () => {
  it("lets a signed-in user with an expired access token through (no access cookie sent)", () => {
    const res = proxy(page("/users", { [`${AUTH_COOKIE_PREFIX}_session`]: "1" }));
    expect(passed(res)).toBe(true);
    expect(getRedirectUrl(res)).toBeNull();
  });

  it("accepts the __Host- spelling used over HTTPS", () => {
    expect(passed(proxy(page("/users", { [`__Host-${AUTH_COOKIE_PREFIX}_session`]: "1" })))).toBe(true);
  });

  it("redirects to sign-in with a safe next when the marker is absent", () => {
    const res = proxy(page("/users/abc?tab=roles"));
    expect(res.status).toBe(307);
    const target = new URL(getRedirectUrl(res)!);
    expect(target.pathname).toBe("/login");
    expect(target.searchParams.get("next")).toBe("/users/abc?tab=roles");
  });

  it("never treats an access or refresh cookie as signed in", () => {
    const res = proxy(page("/users", { [`${AUTH_COOKIE_PREFIX}_access`]: "x", [`${AUTH_COOKIE_PREFIX}_refresh`]: "y" }));
    expect(res.status).toBe(307);
  });

  it("renders public pages signed out", () => {
    for (const path of ["/login", "/forgot-password", "/reset-password", "/accept-invitation", "/"]) {
      expect(passed(proxy(page(path)))).toBe(true);
    }
  });

  it("runs on pages, not on the API or build assets", () => {
    const nextConfig = {};
    expect(unstable_doesMiddlewareMatch({ config, nextConfig, url: "/users" })).toBe(true);
    expect(unstable_doesMiddlewareMatch({ config, nextConfig, url: "/api/me/bootstrap/" })).toBe(false);
    expect(unstable_doesMiddlewareMatch({ config, nextConfig, url: "/_next/static/chunk.js" })).toBe(false);
    expect(unstable_doesMiddlewareMatch({ config, nextConfig, url: "/favicon.ico" })).toBe(false);
  });
});
