/**
 * The permission provider fails CLOSED (FRONTEND_PLATFORM § 9, BUILD_ORDER 8.2): a failed fetch
 * yields no permissions and a non-null permissionsError; outside a provider everything is denied.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import { server } from "../../../tests/setup";
import { API_URL } from "./api";
import { Can, PermissionProvider, permissionsFrom, useOptionalPermissions, usePermissions } from "./permissions";
import { makeQueryClient } from "./query/client";

const BOOT = `${API_URL}/api/me/bootstrap/`;

function wrap(ui: ReactNode) {
  const client = makeQueryClient();
  client.setDefaultOptions({ queries: { ...client.getDefaultOptions().queries, retry: false } });
  return render(
    <QueryClientProvider client={client}>
      <PermissionProvider>{ui}</PermissionProvider>
    </QueryClientProvider>,
  );
}

function Probe() {
  const p = usePermissions();
  return (
    <p data-testid="probe">
      {p.status}|{p.can("users.users.view") ? "can" : "cannot"}|{p.permissionsError ? "error" : "no-error"}|
      {p.signedOut ? "signed-out" : "-"}
    </p>
  );
}

const ok = (permissions: string[]) =>
  HttpResponse.json({
    user: { public_id: "u1", email: "a@example.test", is_superuser: false },
    permissions,
    session: { expires_at: "x", idle_expires_at: "x" },
    server_time: "x",
    degraded: [],
  });

describe("PermissionProvider", () => {
  it("grants exactly the effective set once bootstrap answers", async () => {
    server.use(http.get(BOOT, () => ok(["users.users.view"])));
    wrap(<Probe />);
    expect(await screen.findByText(/^ready\|can\|no-error/)).toBeInTheDocument();
  });

  it("fails closed on a server error: nothing granted, permissionsError set", async () => {
    server.use(http.get(BOOT, () => HttpResponse.json({ error: { code: "server_error", message: "boom" } }, { status: 500 })));
    wrap(<Probe />);
    expect(await screen.findByText(/^error\|cannot\|error\|/)).toBeInTheDocument();
  });

  it("reports signed out on a 401 the refresh could not recover, still denying everything", async () => {
    server.use(
      http.get(BOOT, () => HttpResponse.json({ error: { code: "not_authenticated", message: "x" } }, { status: 401 })),
      http.post(`${API_URL}/api/auth/refresh/`, () => new HttpResponse(null, { status: 401 })),
    );
    wrap(<Probe />);
    expect(await screen.findByText(/^error\|cannot\|error\|\s*signed-out/)).toBeInTheDocument();
  });

  it("denies everything while loading", () => {
    server.use(http.get(BOOT, () => new Promise(() => {})));
    wrap(<Probe />);
    expect(screen.getByTestId("probe")).toHaveTextContent(/^loading\|cannot/);
  });
});

describe("outside a provider", () => {
  it("usePermissions throws", () => {
    const Bad = () => {
      usePermissions();
      return null;
    };
    expect(() => render(<Bad />)).toThrow(/outside <PermissionProvider>/);
  });

  it("useOptionalPermissions denies everything", () => {
    const Shared = () => <p>{useOptionalPermissions().can("users.users.view") ? "shown" : "hidden"}</p>;
    render(<Shared />);
    expect(screen.getByText("hidden")).toBeInTheDocument();
  });
});

describe("<Can>", () => {
  it("renders a visible denied card, never nothing, when the code is not held", async () => {
    server.use(http.get(BOOT, () => ok([])));
    wrap(<Can perm="users.users.view">secret</Can>);
    expect(await screen.findByText(/don't have permission/)).toBeInTheDocument();
    expect(screen.queryByText("secret")).toBeNull();
  });

  it("renders children when the code is held", async () => {
    server.use(http.get(BOOT, () => ok(["users.users.view"])));
    wrap(<Can perm="users.users.view">secret</Can>);
    expect(await screen.findByText("secret")).toBeInTheDocument();
  });
});

describe("permissionsFrom", () => {
  it("canAll of nothing grants nothing", () => {
    const p = permissionsFrom(["a.b.c"]);
    expect(p.canAll([])).toBe(false);
    expect(p.canAny(["x.y.z", "a.b.c"])).toBe(true);
  });
});
