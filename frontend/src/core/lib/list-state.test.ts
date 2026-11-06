import { describe, expect, it } from "vitest";

import { listStateToParams, parseListState } from "./list-state";

const parse = (qs: string, keys: string[] = []) => parseListState(new URLSearchParams(qs), keys);

describe("list state in the URL", () => {
  it("parses page, search, ordering and declared filters only", () => {
    expect(parse("page=3&search=%20ada%20&ordering=-email&status=active&evil=1", ["status"])).toEqual({
      page: 3,
      search: "ada",
      ordering: "-email",
      filters: { status: "active" },
    });
  });

  it.each(["page=0", "page=-2", "page=abc", ""])("falls back to page 1 for %j", (qs) => {
    expect(parse(qs).page).toBe(1);
  });

  it.each(["email;drop", "-", "a b", "../x"])("drops an ordering that is not a field name: %j", (ordering) => {
    expect(parse(`ordering=${encodeURIComponent(ordering)}`).ordering).toBeNull();
  });

  it("refuses a filter named like a reserved key", () => {
    expect(() => parse("", ["page"])).toThrow(/reserved/);
  });

  it("writes the shortest canonical query, defaults omitted, filters sorted", () => {
    expect(listStateToParams({ page: 1, search: "", ordering: null, filters: {} }).toString()).toBe("");
    expect(
      listStateToParams({ page: 2, search: "ada", ordering: "email", filters: { z: "1", a: "2" } }).toString(),
    ).toBe("page=2&search=ada&ordering=email&a=2&z=1");
  });

  it("round-trips", () => {
    const state = { page: 4, search: "x", ordering: "-created_at", filters: { role: "staff" } };
    expect(parseListState(listStateToParams(state), ["role"])).toEqual(state);
  });
});
