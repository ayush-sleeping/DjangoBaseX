import { describe, expect, it } from "vitest";

import { HSTS_VALUE, securityHeaders } from "./headers";

const asMap = (isProduction: boolean) =>
  Object.fromEntries(securityHeaders({ isProduction }).map((h) => [h.key, h.value]));

describe("securityHeaders", () => {
  it("sets every static header with its value", () => {
    const h = asMap(true);
    expect(h["X-Content-Type-Options"]).toBe("nosniff");
    expect(h["X-Frame-Options"]).toBe("DENY");
    expect(h["Referrer-Policy"]).toBe("strict-origin-when-cross-origin");
    expect(h["Permissions-Policy"]).toBe("camera=(), microphone=(), geolocation=(), payment=()");
    expect(h["Cross-Origin-Opener-Policy"]).toBe("same-origin");
    expect(h["X-XSS-Protection"]).toBe("0");
    expect(h["Strict-Transport-Security"]).toBe("max-age=63072000; includeSubDomains");
    expect(h["Strict-Transport-Security"]).toBe(HSTS_VALUE);
  });

  it("sends HSTS in production only", () => {
    expect(asMap(false)["Strict-Transport-Security"]).toBeUndefined();
    expect(Object.keys(asMap(false))).toHaveLength(6);
  });

  it("has no duplicate keys and never carries the nonce CSP (proxy.ts owns it)", () => {
    const keys = securityHeaders({ isProduction: true }).map((h) => h.key);
    expect(new Set(keys).size).toBe(keys.length);
    expect(keys.some((k) => k.startsWith("Content-Security-Policy"))).toBe(false);
  });
});
