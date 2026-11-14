import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { buildCsp, parseCspMode, parseExtraOrigins, parseReportUrl } from "./csp";

const NONCE = "YWJjZA==";
const directive = (policy: string, name: string) =>
  policy.split("; ").find((d) => d === name || d.startsWith(`${name} `));

describe("buildCsp (§ 18)", () => {
  const prod = buildCsp({ nonce: NONCE, isDev: false });

  it("carries the fixed directives", () => {
    expect(directive(prod, "default-src")).toBe("default-src 'self'");
    expect(directive(prod, "script-src")).toBe(`script-src 'self' 'nonce-${NONCE}' 'strict-dynamic'`);
    expect(directive(prod, "object-src")).toBe("object-src 'none'");
    expect(directive(prod, "base-uri")).toBe("base-uri 'self'");
    expect(directive(prod, "form-action")).toBe("form-action 'self'");
    expect(directive(prod, "frame-ancestors")).toBe("frame-ancestors 'none'");
    expect(directive(prod, "img-src")).toBe("img-src 'self' data: blob:");
    expect(directive(prod, "connect-src")).toBe("connect-src 'self'");
  });

  it("keeps style-src on unsafe-inline with no style nonce", () => {
    expect(directive(prod, "style-src")).toBe("style-src 'self' 'unsafe-inline'");
  });

  it("allows unsafe-eval only in development, and upgrades insecure requests only in production", () => {
    const dev = buildCsp({ nonce: NONCE, isDev: true });
    expect(directive(dev, "script-src")).toContain("'unsafe-eval'");
    expect(prod).not.toContain("unsafe-eval");
    expect(prod).toContain("upgrade-insecure-requests");
    expect(dev).not.toContain("upgrade-insecure-requests");
  });

  it("adds extra origins to img-src and connect-src only", () => {
    const policy = buildCsp({ nonce: NONCE, isDev: false, extraOrigins: ["https://cdn.example.test"] });
    expect(directive(policy, "img-src")).toContain("https://cdn.example.test");
    expect(directive(policy, "connect-src")).toContain("https://cdn.example.test");
    expect(directive(policy, "script-src")).not.toContain("example.test");
  });

  it("adds report-uri and report-to only when a report URL is given", () => {
    expect(prod).not.toContain("report-");
    const policy = buildCsp({ nonce: NONCE, isDev: false, reportUrl: "/api/public/csp-report/" });
    expect(directive(policy, "report-uri")).toBe("report-uri /api/public/csp-report/");
    expect(directive(policy, "report-to")).toBe("report-to csp");
  });

  it("refuses a nonce that is not base64", () => {
    expect(() => buildCsp({ nonce: "a'; script-src *", isDev: false })).toThrow();
  });
});

describe("parseCspMode", () => {
  it.each([
    ["off", "off"],
    ["enforce", "enforce"],
    ["report_only", "report_only"],
    [" ENFORCE ", "enforce"],
    [undefined, "report_only"],
    ["", "report_only"],
    ["strict", "report_only"],
  ])("%j → %s", (raw, expected) => expect(parseCspMode(raw)).toBe(expected));
});

describe("parseExtraOrigins", () => {
  it("accepts bare origins, trims and de-duplicates", () => {
    expect(parseExtraOrigins(" https://a.example.test , https://a.example.test/,wss://b.example.test:8443")).toEqual([
      "https://a.example.test",
      "wss://b.example.test:8443",
    ]);
  });

  it.each([
    "javascript:alert(1)",
    "https://a.example.test/path",
    "https://a.example.test?x=1",
    "https://*.example.test",
    "https://a.example.test 'unsafe-inline'",
    "a.example.test",
    "data:",
    "https://",
  ])("drops %j and reports it", (bad) => {
    const seen: string[] = [];
    expect(parseExtraOrigins(bad, (e) => seen.push(e))).toEqual([]);
    expect(seen).toHaveLength(1);
  });

  it("is empty for an unset variable", () => expect(parseExtraOrigins(undefined)).toEqual([]));
});

describe("parseReportUrl", () => {
  it("accepts a root-relative path or an absolute URL", () => {
    expect(parseReportUrl("/api/public/csp-report/")).toBe("/api/public/csp-report/");
    expect(parseReportUrl("https://r.example.test/csp")).toBe("https://r.example.test/csp");
  });
  it.each([undefined, "", "//evil.example.test/x", "javascript:x", "/a; script-src *", "relative/path"])(
    "refuses %j",
    (bad) => expect(parseReportUrl(bad)).toBeUndefined(),
  );
});

describe("no origin literal in the policy sources", () => {
  const scheme = /https?:\/\//;
  it.each(["./csp.ts", "../../../proxy.ts"])("%s names no http(s) origin", (file) => {
    expect(readFileSync(new URL(file, import.meta.url), "utf8")).not.toMatch(scheme);
  });
});
