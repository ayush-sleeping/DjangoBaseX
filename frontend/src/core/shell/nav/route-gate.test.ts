/**
 * The route gate's decisions (FRONTEND_PLATFORM § 10, BUILD_ORDER 8.2 acceptance (a), runtime
 * half): no navigation entry → denied; public → rendered signed out; lacking the entry's code →
 * denied, and a filtered-out deep entry never falls back to a shallower one the user holds.
 */
import { describe, expect, it } from "vitest";

import { permissionsFrom } from "@/core/lib/permissions";

import { decide } from "./route-gate";

const ready = (...codes: string[]) => ({ status: "ready" as const, signedOut: false, ...permissionsFrom(codes) });

describe("decide()", () => {
  it("denies a page with no navigation entry, even for a user holding every code", () => {
    expect(decide("/not-registered", ready("users.users.view", "users.users.create"), []).kind).toBe("no-entry");
  });

  it("allows a public page while permissions are still loading or failed", () => {
    expect(decide("/login", { status: "loading", signedOut: false, can: () => false }, []).kind).toBe("allow");
    expect(decide("/login", { status: "error", signedOut: true, can: () => false }, []).kind).toBe("allow");
  });

  it("denies a page whose code is not held", () => {
    expect(decide("/users", ready(), []).kind).toBe("denied");
  });

  it("matches /users/new to its own entry, not to /users", () => {
    const decision = decide("/users/new", ready("users.users.view"), []);
    expect(decision.kind).toBe("denied");
    expect(decide("/users/new", ready("users.users.view", "users.users.create"), []).kind).toBe("allow");
  });

  it("gates a detail page by its section's prefix", () => {
    expect(decide("/users/7b1e", ready("users.users.view"), []).kind).toBe("allow");
  });

  it("allows a plugin page only through the user's own bootstrap entry", () => {
    const notes = { key: "home", label: "Notes", href: "/notes", permission: "notes.notes.view", hidden: false, public: false, exact: false };
    expect(decide("/notes", ready("notes.notes.view"), []).kind).toBe("no-entry");
    expect(decide("/notes", ready("notes.notes.view"), [notes]).kind).toBe("allow");
  });

  it("waits while loading and fails closed on error", () => {
    expect(decide("/users", { status: "loading", signedOut: false, can: () => true }, []).kind).toBe("loading");
    expect(decide("/users", { status: "error", signedOut: false, can: () => true }, []).kind).toBe("error");
    expect(decide("/users", { status: "error", signedOut: true, can: () => true }, []).kind).toBe("signed-out");
  });
});
