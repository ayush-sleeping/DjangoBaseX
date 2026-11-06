import { describe, expect, it } from "vitest";

import { resolveRoute, type RouteEntry } from "./resolve-route";

const entry = (href: string, extra: Partial<RouteEntry> = {}): RouteEntry => ({
  key: href,
  label: href,
  href,
  permission: null,
  hidden: false,
  public: false,
  exact: false,
  ...extra,
});

const ENTRIES = [
  entry("/", { exact: true }),
  entry("/users", { permission: "users.users.view" }),
  entry("/users/new", { permission: "users.users.create", hidden: true }),
  entry("/login", { public: true, hidden: true }),
];

describe("resolveRoute: the deepest prefix wins, and no match is a denial", () => {
  it.each([
    ["/", "/"],
    ["/users", "/users"],
    ["/users/", "/users"],
    ["/users/0b8f-detail", "/users"],
    ["/users/new", "/users/new"],
    ["/users/new/", "/users/new"],
    ["/users?page=2", "/users"],
    ["/login", "/login"],
  ])("%s → %s", (path, href) => {
    expect(resolveRoute(path, ENTRIES)?.href).toBe(href);
  });

  it.each(["/settings", "/usersx", "/user", "/anything/else"])("%s has no entry: denied", (path) => {
    expect(resolveRoute(path, ENTRIES)).toBeNull();
  });

  it("an exact entry does not own the pages below it", () => {
    expect(resolveRoute("/nope", [entry("/", { exact: true })])).toBeNull();
  });
});
