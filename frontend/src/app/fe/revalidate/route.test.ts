import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { revalidateTag } = vi.hoisted(() => ({ revalidateTag: vi.fn() }));
vi.mock("next/cache", () => ({ revalidateTag }));

import { POST } from "./route";

const SECRET = "s".repeat(32);

function req(body: unknown, secret?: string, raw?: string): Request {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (secret !== undefined) headers["x-revalidate-secret"] = secret;
  return new Request("http://fe.test/fe/revalidate/", {
    method: "POST",
    headers,
    body: raw ?? JSON.stringify(body),
  });
}

describe("POST /fe/revalidate/", () => {
  beforeEach(() => {
    revalidateTag.mockClear();
    vi.stubEnv("REVALIDATE_SECRET", SECRET);
  });
  afterEach(() => vi.unstubAllEnvs());

  it("refuses everything when no secret is configured", async () => {
    vi.stubEnv("REVALIDATE_SECRET", "");
    expect((await POST(req({ tags: ["identity"] }, ""))).status).toBe(401);
    expect((await POST(req({ tags: ["identity"] }, "anything"))).status).toBe(401);
    expect(revalidateTag).not.toHaveBeenCalled();
  });

  it("401 on a missing or wrong secret", async () => {
    expect((await POST(req({ tags: ["identity"] }))).status).toBe(401);
    expect((await POST(req({ tags: ["identity"] }, "x".repeat(32)))).status).toBe(401);
    expect(revalidateTag).not.toHaveBeenCalled();
  });

  it("401, without throwing, on a secret of a different length", async () => {
    expect((await POST(req({ tags: ["identity"] }, "short"))).status).toBe(401);
    expect((await POST(req({ tags: ["identity"] }, SECRET + "x"))).status).toBe(401);
    expect(revalidateTag).not.toHaveBeenCalled();
  });

  it("400 on a bad body, after the secret check", async () => {
    expect((await POST(req(null, SECRET, "not json"))).status).toBe(400);
    expect((await POST(req({}, SECRET))).status).toBe(400);
    expect((await POST(req({ tags: [] }, SECRET))).status).toBe(400);
    expect((await POST(req({ tags: ["users"] }, SECRET))).status).toBe(400);
    expect((await POST(req({ tags: [1] }, SECRET))).status).toBe(400);
    expect(revalidateTag).not.toHaveBeenCalled();
  });

  it("204 and revalidates each identity tag immediately", async () => {
    const res = await POST(req({ tags: ["identity", "identity:app.example.test"] }, SECRET));
    expect(res.status).toBe(204);
    expect(revalidateTag).toHaveBeenCalledTimes(2);
    expect(revalidateTag).toHaveBeenCalledWith("identity", { expire: 0 });
    expect(revalidateTag).toHaveBeenCalledWith("identity:app.example.test", { expire: 0 });
  });
});
