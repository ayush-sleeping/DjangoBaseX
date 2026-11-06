/**
 * BUILD_ORDER 8.2 acceptance (b), second half: once the proxy has let the page render (the marker
 * was present), the signed-in user whose access token has expired is REFRESHED, not bounced. The
 * first API call answers 401, the transport refreshes once, replays, and the caller sees the data.
 */
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "../../../../tests/setup";
import { fetchBootstrap } from "../bootstrap";
import { API_URL } from "./client";

const BOOT = `${API_URL}/api/me/bootstrap/`;
const REFRESH = `${API_URL}/api/auth/refresh/`;

describe("an expired access token is refreshed, not bounced", () => {
  it("401 → one refresh → replay → 200", async () => {
    let refreshed = false;
    let refreshCalls = 0;
    server.use(
      http.get(BOOT, () =>
        refreshed
          ? HttpResponse.json({ user: { email: "a@example.test" }, permissions: ["users.users.view"], degraded: [] })
          : HttpResponse.json({ error: { code: "not_authenticated", message: "expired" } }, { status: 401 }),
      ),
      http.post(REFRESH, () => {
        refreshCalls += 1;
        refreshed = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );

    const boot = await fetchBootstrap();

    expect(boot.permissions).toEqual(["users.users.view"]);
    expect(refreshCalls).toBe(1);
  });

  it("a failed refresh surfaces the 401 (signed out), and is attempted once", async () => {
    let refreshCalls = 0;
    server.use(
      http.get(BOOT, () => HttpResponse.json({ error: { code: "not_authenticated", message: "x" } }, { status: 401 })),
      http.post(REFRESH, () => {
        refreshCalls += 1;
        return HttpResponse.json({ error: { code: "not_authenticated", message: "x" } }, { status: 401 });
      }),
    );

    await expect(fetchBootstrap()).rejects.toMatchObject({ status: 401 });
    expect(refreshCalls).toBe(1);
  });
});
