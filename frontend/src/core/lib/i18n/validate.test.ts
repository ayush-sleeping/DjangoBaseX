/**
 * Translations that are present but wrong (BUILD_ORDER 8.4d): the load-time shape guard keeps the
 * source copy for the one key, and the test-time validator refuses it before it ships. Plus the
 * development warnings, once each, on the client and the server alike.
 */
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { API_URL } from "@/core/lib/api";

import { server } from "../../../../tests/setup";
import { mergeMessages, messageShape, resetWarnings, sameShape, warnOnce } from "./messages";
import { getServerT } from "./server";
import { catalogueProblems } from "./validate";

const SOURCE = {
  notes: {
    count: "{count, plural, one {# note} other {# notes}}",
    sent: "Sent <date></date> to {email}",
    title: "Notes",
  },
};

afterEach(() => {
  resetWarnings();
  vi.restoreAllMocks();
});

describe("messageShape", () => {
  it("reads arguments, their types and tags, ignoring branch text", () => {
    expect(messageShape(SOURCE.notes.count)).toBe("arg:count:plural");
    expect(messageShape(SOURCE.notes.sent)).toBe("arg:email|tag:date");
    expect(messageShape("{count, plural, one {Feld} other {{count, number} Felder}}")).toBe("arg:count:number|arg:count:plural");
    expect(messageShape("{n, number, ::percent} done")).toBe("arg:n:number");
  });

  it("refuses what does not parse", () => {
    expect(messageShape("{count, plural, one {# Notiz} few {# Notizen}}")).toBeNull(); // no `other`
    expect(messageShape("{kind, select, a {A} b {B}}")).toBeNull();
    expect(messageShape("Hello {name")).toBeNull();
    expect(messageShape("Hello name}")).toBeNull();
    expect(messageShape("{count, plural, one}")).toBeNull();
  });

  it("compares a translation with its source", () => {
    expect(sameShape(SOURCE.notes.count, "{count, plural, one {# Notiz} other {# Notizen}}")).toBe(true);
    expect(sameShape(SOURCE.notes.sent, "Am <date></date> an {email} gesendet")).toBe(true);
    expect(sameShape(SOURCE.notes.sent, "Am <date></date> gesendet")).toBe(false); // {email} dropped
    expect(sameShape(SOURCE.notes.sent, "Gesendet an {mail}")).toBe(false); // renamed, tag lost
  });
});

describe("the load-time guard", () => {
  it("keeps the source copy for a malformed or mismatched translation, and warns once", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const merged = mergeMessages(SOURCE, { notes: { title: "Notizen", sent: "Gesendet", count: "{count, plural, one {# Notiz}" } });
    expect(merged.notes.title).toBe("Notizen");
    expect(merged.notes.sent).toBe(SOURCE.notes.sent);
    expect(merged.notes.count).toBe(SOURCE.notes.count);
    expect(warn).toHaveBeenCalledTimes(2);
    mergeMessages(SOURCE, { notes: { sent: "Gesendet" } });
    expect(warn).toHaveBeenCalledTimes(2); // once per distinct problem, not per render
  });
});

describe("merging is data, never code", () => {
  it("skips keys that name the prototype chain", () => {
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const hostile = JSON.parse('{"__proto__": {"polluted": "yes"}, "constructor": {"x": "y"}, "notes": {"title": "Notizen", "__proto__": {"p": "q"}}}');
    const merged = mergeMessages(SOURCE, hostile);
    expect(merged.notes.title).toBe("Notizen");
    expect(Object.getPrototypeOf(merged)).toBe(Object.prototype);
    expect(Object.getPrototypeOf(merged.notes)).toBe(Object.prototype);
    expect(({} as Record<string, unknown>).polluted).toBeUndefined();
    expect(Object.keys(merged)).toEqual(["notes"]);
  });

  it("keeps the source for a translated plural with no `other` branch (load time, not only in tests)", () => {
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const merged = mergeMessages(SOURCE, { notes: { count: "{count, plural, one {# Notiz} few {# Notizen}}" } });
    expect(merged.notes.count).toBe(SOURCE.notes.count);
  });
});

describe("the strict validator (positive controls)", () => {
  it("passes a good translation", () => {
    const de = { notes: { title: "Notizen", count: "{count, plural, one {# Notiz} other {# Notizen}}" } };
    expect(catalogueProblems(SOURCE, de, "de")).toEqual([]);
    expect(catalogueProblems(SOURCE, SOURCE, "en")).toEqual([]);
  });

  it("refuses a translation missing an argument", () => {
    expect(catalogueProblems(SOURCE, { notes: { sent: "Am <date></date> gesendet" } }, "de")).toEqual([
      "notes.sent: its arguments or tags differ from the source, or it does not parse",
    ]);
  });

  it("refuses unbalanced braces", () => {
    expect(catalogueProblems(SOURCE, { notes: { title: "Notizen {" } }, "de")).toHaveLength(1);
  });

  it("refuses a plural with no `other` branch, which only formatting reveals", () => {
    const problems = catalogueProblems(SOURCE, { notes: { count: "{count, plural, one {# Notiz} few {# Notizen}}" } }, "de");
    expect(problems).toHaveLength(1);
    expect(problems[0]).toMatch(/^notes\.count: /);
  });

  it("refuses a stale key", () => {
    expect(catalogueProblems(SOURCE, { notes: { gone: "Weg" } }, "de")).toEqual(["notes.gone: not in the source catalogue (a stale key)"]);
  });
});

describe("warnings", () => {
  it("warnOnce warns once per distinct text", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    warnOnce("a");
    warnOnce("a");
    warnOnce("b");
    expect(warn).toHaveBeenCalledTimes(2);
  });

  it("getServerT renders a missing key as its path and warns once in development", async () => {
    server.use(http.get(`${API_URL}/api/public/config/`, () => HttpResponse.json({ product_name: "P", tagline: "", locale: "en", timezone: "UTC" })));
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const t = (await getServerT("users.index")) as unknown as (key: string) => string;
    expect(t("nope")).toBe("users.index.nope");
    expect(t("nope")).toBe("users.index.nope");
    expect(warn).toHaveBeenCalledTimes(1);
    expect((await getServerT("users.index"))("title")).toBe("Users");
  });
});
