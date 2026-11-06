import { describe, expect, it } from "vitest";

import { safeNext } from "./safe-next";

describe("safeNext: only a same-origin relative path survives", () => {
  it.each([
    ["/users", "/users"],
    ["/users/abc?tab=roles", "/users/abc?tab=roles"],
    ["/settings/roles#x", "/settings/roles#x"],
  ])("keeps %s", (input, expected) => {
    expect(safeNext(input)).toBe(expected);
  });

  it.each([
    null,
    undefined,
    "",
    "users",
    "https://evil.example/",
    "//evil.example",
    "///evil.example",
    "/\\evil.example",
    "\\\\evil.example",
    "/\t/evil.example",
    "/\n/evil.example",
    "javascript:alert(1)",
    "http:/evil.example",
    " /users",
  ])("refuses %j", (input) => {
    expect(safeNext(input)).toBe("/");
  });
});
