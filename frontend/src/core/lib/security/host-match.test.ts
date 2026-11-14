import { describe, expect, it } from "vitest";

import { classifyHost, normalizeHost } from "./host-match";

const known = { primary: "app.example.test", allowed: ["Admin.Example.Test."] };

describe("normalizeHost", () => {
  it("lowercases and strips the port and a trailing dot", () => {
    expect(normalizeHost("APP.Example.Test:8443")).toBe("app.example.test");
    expect(normalizeHost("app.example.test.")).toBe("app.example.test");
    expect(normalizeHost("app.example.test.:443")).toBe("app.example.test");
  });
  it("refuses what is not a host name", () => {
    for (const bad of [null, undefined, "", "a b", "app.example.test/x", "[::1]", "a..b", "-a.test", "a@b.test"]) {
      expect(normalizeHost(bad)).toBeNull();
    }
  });
});

describe("classifyHost", () => {
  it("matches the primary and allowed hosts exactly", () => {
    expect(classifyHost("app.example.test", known)).toBe("platform");
    expect(classifyHost("APP.EXAMPLE.TEST:3000", known)).toBe("platform");
    expect(classifyHost("admin.example.test", known)).toBe("platform");
  });
  it("refuses look-alikes", () => {
    for (const bad of [
      "not-app.example.test",
      "app.example.test.attacker.example",
      "attacker.example/app.example.test",
      "xapp.example.test",
      "app.example.test.evil",
      "example.test",
      "sub.app.example.test",
    ]) {
      expect(classifyHost(bad, known)).toBe("unknown");
    }
    expect(classifyHost(null, known)).toBe("unknown");
  });
});
