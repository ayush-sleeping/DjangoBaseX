/**
 * The marker regression test (FRONTEND_PLATFORM § 8.2, BUILD_ORDER 8.2 acceptance (b), first
 * half): a signed-in user whose access token has expired navigates to a page. The browser sends
 * only the Path=/ marker — the /api/-scoped access cookie and the refresh-scoped refresh cookie are
 * not sent on a page request — and the proxy must let the page render, not bounce to sign-in.
 */
// The installed Next exports unstable_doesMiddlewareMatch; its proxy.md names it unstable_doesProxyMatch.
import { getRedirectUrl, unstable_doesMiddlewareMatch } from "next/experimental/testing/server";
import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

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

describe("proxy: the per-request CSP (§ 18, BUILD_ORDER 8.5)", () => {
  const SIGNED_IN = { [`${AUTH_COOKIE_PREFIX}_session`]: "1" };
  const requestHeader = (res: Response, name: string) =>
    res.headers.get(`x-middleware-request-${name.toLowerCase()}`);
  const nonceOf = (res: Response) => requestHeader(res, "x-nonce");

  afterEach(() => vi.unstubAllEnvs());

  it("mints a different nonce per request and puts it in the request policy", () => {
    vi.stubEnv("CSP_MODE", "report_only");
    const one = proxy(page("/users", SIGNED_IN));
    const two = proxy(page("/users", SIGNED_IN));
    expect(nonceOf(one)).toBeTruthy();
    expect(nonceOf(one)).not.toBe(nonceOf(two));
    expect(requestHeader(one, "content-security-policy")).toContain(`'nonce-${nonceOf(one)}'`);
  });

  it("sets the request policy and the response header with the same value (report_only is the default)", () => {
    vi.stubEnv("CSP_MODE", "");
    const res = proxy(page("/users", SIGNED_IN));
    const policy = res.headers.get("Content-Security-Policy-Report-Only");
    expect(policy).toContain("default-src 'self'");
    expect(requestHeader(res, "content-security-policy")).toBe(policy);
    expect(res.headers.get("Content-Security-Policy")).toBeNull();
  });

  it("enforce sends the enforcing header only", () => {
    vi.stubEnv("CSP_MODE", "enforce");
    const res = proxy(page("/users", SIGNED_IN));
    expect(res.headers.get("Content-Security-Policy")).toContain("script-src");
    expect(res.headers.get("Content-Security-Policy-Report-Only")).toBeNull();
    expect(requestHeader(res, "content-security-policy")).toBe(res.headers.get("Content-Security-Policy"));
  });

  it("off sends no policy, on request or response", () => {
    vi.stubEnv("CSP_MODE", "off");
    const res = proxy(page("/users", SIGNED_IN));
    expect(res.headers.get("Content-Security-Policy")).toBeNull();
    expect(res.headers.get("Content-Security-Policy-Report-Only")).toBeNull();
    expect(requestHeader(res, "content-security-policy")).toBeNull();
    expect(passed(res)).toBe(true);
  });

  it("an unknown mode is report_only and never throws", () => {
    vi.stubEnv("CSP_MODE", "banana");
    const res = proxy(page("/users", SIGNED_IN));
    expect(res.headers.get("Content-Security-Policy-Report-Only")).toBeTruthy();
    expect(res.headers.get("Content-Security-Policy")).toBeNull();
  });

  it("reads CSP_MODE at call time: flipping it between two calls changes the header, no rebuild", () => {
    vi.stubEnv("CSP_MODE", "report_only");
    const before = proxy(page("/users", SIGNED_IN));
    vi.stubEnv("CSP_MODE", "enforce");
    const after = proxy(page("/users", SIGNED_IN));
    expect(before.headers.get("Content-Security-Policy-Report-Only")).toBeTruthy();
    expect(before.headers.get("Content-Security-Policy")).toBeNull();
    expect(after.headers.get("Content-Security-Policy")).toBeTruthy();
    expect(after.headers.get("Content-Security-Policy-Report-Only")).toBeNull();
  });

  it("takes extra origins and the report URL from the runtime environment", () => {
    vi.stubEnv("CSP_MODE", "enforce");
    vi.stubEnv("CSP_EXTRA_ORIGINS", "https://cdn.example.test,not-an-origin");
    vi.stubEnv("CSP_REPORT_URL", "/api/public/csp-report/");
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const res = proxy(page("/users", SIGNED_IN));
    expect(warn).toHaveBeenCalledWith(expect.stringContaining("not-an-origin"));
    warn.mockRestore();
    const policy = res.headers.get("Content-Security-Policy")!;
    expect(policy).toContain("img-src 'self' data: blob: https://cdn.example.test");
    expect(policy).not.toContain("not-an-origin");
    expect(policy).toContain("report-uri /api/public/csp-report/");
    expect(res.headers.get("Reporting-Endpoints")).toBe('csp="/api/public/csp-report/"');
  });

  it("carries the policy on public pages too, and not on the sign-in redirect", () => {
    vi.stubEnv("CSP_MODE", "enforce");
    expect(proxy(page("/login")).headers.get("Content-Security-Policy")).toBeTruthy();
    const redirect = proxy(page("/users"));
    expect(redirect.status).toBe(307);
    expect(redirect.headers.get("Content-Security-Policy")).toBeNull();
  });

  it("leaves a prefetch without a nonce or policy (it is not a rendered document)", () => {
    vi.stubEnv("CSP_MODE", "enforce");
    const prefetch = new NextRequest(`${ORIGIN}/users`, {
      headers: { cookie: `${AUTH_COOKIE_PREFIX}_session=1`, "next-router-prefetch": "1" },
    });
    const res = proxy(prefetch);
    expect(passed(res)).toBe(true);
    expect(res.headers.get("Content-Security-Policy")).toBeNull();
    expect(nonceOf(res)).toBeNull();
  });
});
