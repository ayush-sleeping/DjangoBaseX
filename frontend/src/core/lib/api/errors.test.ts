import { describe, expect, it } from "vitest";

import { ApiError, decodeError, flattenFields, isApiError, kindFor, messageFor, retryAfterFrom } from "./errors";

function response(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), { status, headers });
}

const envelope = (error: Record<string, unknown>) => ({ error });

describe("decodeError", () => {
  it("maps each status to its kind and keeps status, code, request id, method and path", async () => {
    const cases: Array<[number, Record<string, unknown>, string]> = [
      [401, { code: "not_authenticated" }, "unauthenticated"],
      [423, { code: "reauth_required", action_key: "mfa_disable" }, "reauth_required"],
      [403, { code: "permission_denied" }, "permission"],
      [403, { code: "mfa_enrollment_required" }, "entitlement"],
      [403, { code: "plan_limit", remediation_url: "/billing" }, "entitlement"],
      [402, { code: "payment_required" }, "payment_required"],
      [404, { code: "not_found" }, "not_found"],
      [409, { code: "conflict" }, "conflict"],
      [412, { code: "stale" }, "conflict"],
      [400, { code: "invalid" }, "validation"],
      [429, { code: "throttled" }, "rate_limited"],
      [503, { code: "server_error" }, "server"],
      [415, { code: "unsupported" }, "server"],
    ];
    for (const [status, body, kind] of cases) {
      const err = await decodeError(response(status, envelope({ request_id: "rid1", ...body })), "POST", "/api/x/");
      expect(err.kind, `${status}`).toBe(kind);
      expect([err.status, err.code, err.requestId, err.method, err.path]).toEqual([
        status,
        body.code,
        "rid1",
        "POST",
        "/api/x/",
      ]);
    }
  });

  it("carries the re-auth action key and the entitlement remediation", async () => {
    const reauth = await decodeError(response(423, envelope({ code: "reauth_required", action_key: "k" })), "POST", "/p");
    expect(reauth.actionKey).toBe("k");
    const ent = await decodeError(
      response(403, envelope({ code: "onboarding_incomplete", unmet: ["profile", "plan"], remediation_url: "/go" })),
      "GET",
      "/p",
    );
    expect([ent.unmet, ent.remediationUrl]).toEqual([["profile", "plan"], "/go"]);
  });

  it("flattens nested field paths exactly and separates non-field errors", async () => {
    const err = await decodeError(
      response(
        400,
        envelope({
          code: "invalid",
          details: {
            email: ["Enter a valid email."],
            lines: [{}, {}, { quantity: ["must be ≤ 2000"] }],
            non_field_errors: ["Start must precede end."],
          },
        }),
      ),
      "POST",
      "/p",
    );
    expect(err.fields).toEqual([
      { path: "email", message: "Enter a valid email.", code: "invalid" },
      { path: "lines.2.quantity", message: "must be ≤ 2000", code: "invalid" },
    ]);
    expect(err.nonField).toEqual(["Start must precede end."]);
  });

  it("survives a non-JSON body", async () => {
    const err = await decodeError(new Response("<html>", { status: 502 }), "GET", "/p");
    expect([err.kind, err.code, err.status]).toEqual(["server", "http_502", 502]);
  });
});

describe("retryAfterFrom", () => {
  it("prefers the body, then delta-seconds, then an HTTP-date, and clamps", () => {
    const now = Date.parse("2026-10-24T10:00:00Z");
    expect(retryAfterFrom(12, "30", now)).toBe(12);
    expect(retryAfterFrom(undefined, "30", now)).toBe(30);
    expect(retryAfterFrom(undefined, "Sat, 24 Oct 2026 10:00:45 GMT", now)).toBe(45);
    expect(retryAfterFrom(undefined, "Sat, 24 Oct 2026 09:00:00 GMT", now)).toBe(0);
    expect(retryAfterFrom(undefined, "999999", now)).toBe(3600);
    expect(retryAfterFrom(undefined, "garbage", now)).toBeUndefined();
    expect(retryAfterFrom(undefined, null, now)).toBeUndefined();
  });
});

describe("messageFor", () => {
  it("never stringifies structured detail", () => {
    const objects: unknown[] = [{ a: 1 }, ["x"], { message: { nested: true } }, null, 42];
    for (const detail of objects) {
      const err = new ApiError({ kind: "server", status: 503, code: "weird", method: "GET", path: "/p", details: detail });
      const copy = messageFor(err);
      expect(copy).not.toContain("[object");
      expect(copy).not.toContain("{");
      expect(copy).toBe("Something went wrong (HTTP 503).");
    }
  });

  it("lets the server message win, then the code map", () => {
    expect(messageFor(new ApiError({ kind: "server", status: 500, code: "server_error", message: "Custom", method: "GET", path: "/p" }))).toBe("Custom");
    expect(messageFor(new ApiError({ kind: "rate_limited", status: 429, code: "throttled", method: "GET", path: "/p" }))).toMatch(/Too many/);
  });
});

describe("isApiError", () => {
  it("accepts a cross-realm error by brand, not instanceof", () => {
    const foreign = { __djx_api_error__: true, kind: "network", status: 0, code: "network" };
    expect(isApiError(foreign)).toBe(true);
    expect(isApiError(new Error("x"))).toBe(false);
    expect(isApiError(null)).toBe(false);
  });

  it("kindFor treats a 403 with a remediation as entitlement", () => {
    expect(kindFor(403, "anything", { remediation_url: "/x" })).toBe("entitlement");
    expect(kindFor(403, "anything", {})).toBe("permission");
    expect(flattenFields(null)).toEqual([]);
  });
});
