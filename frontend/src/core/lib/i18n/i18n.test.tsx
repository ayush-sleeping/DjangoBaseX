/**
 * The catalogues and the provider (FRONTEND_PLATFORM § 22, BUILD_ORDER 8.4c): a translation falls
 * back to the source KEY BY KEY, ICU plurals follow the locale's own rules, and the provider takes
 * the viewer's locale from the same place as the formatters (bootstrap, then the platform).
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { createTranslator } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import { API_URL } from "@/core/lib/api";
import { LocalizationProvider } from "@/core/lib/format/use-format";
import { makeQueryClient } from "@/core/lib/query/client";

import { server } from "../../../../tests/setup";
import { I18nProvider, useT } from "./index";
import { candidates, catalogueFor, loadMessages, type Messages, mergeMessages, missingMessage, SOURCE_MESSAGES } from "./messages";

const BOOT = `${API_URL}/api/me/bootstrap/`;

/** A partial translation: two keys, and one key the source no longer has. */
const PARTIAL = {
  shells: { form: { discard: "Verwerfen", fieldsNeedAttention: "{count, plural, one {# Feld} other {# Felder}} prüfen." }, gone: "x" },
} as unknown as Partial<Messages>;

describe("catalogue resolution", () => {
  it("tries the most specific tag first", () => {
    expect(candidates("de-AT")).toEqual(["de-AT", "de"]);
    expect(candidates("zh-Hant-TW")).toEqual(["zh-Hant-TW", "zh-Hant", "zh"]);
  });

  it("picks a catalogue only when one exists, and none for the source language", () => {
    const catalogues = { de: async () => PARTIAL };
    expect(catalogueFor("de-AT", catalogues)).toBe("de");
    expect(catalogueFor("fr-FR", catalogues)).toBeNull();
    expect(catalogueFor("en-IN", catalogues)).toBeNull();
  });

  it("merges key by key: translated keys win, the rest keep the source, stale keys are dropped", () => {
    const merged = mergeMessages(SOURCE_MESSAGES, PARTIAL);
    expect(merged.shells.form.discard).toBe("Verwerfen");
    expect(merged.shells.form.save).toBe(SOURCE_MESSAGES.shells.form.save);
    expect((merged.shells as Record<string, unknown>).gone).toBeUndefined();
    expect(SOURCE_MESSAGES.shells.form.discard).toBe("Discard"); // the source is never mutated
  });

  it("loads lazily, and an unloadable catalogue falls back to the source instead of failing", async () => {
    expect((await loadMessages("de-DE", { de: async () => PARTIAL })).shells.form.discard).toBe("Verwerfen");
    expect(await loadMessages("de-DE", { de: async () => Promise.reject(new Error("chunk")) })).toBe(SOURCE_MESSAGES);
    expect(await loadMessages("en-US")).toBe(SOURCE_MESSAGES);
  });

  it("renders a key missing everywhere as its path, visibly", () => {
    expect(missingMessage({ namespace: "users.show", key: "nope" })).toBe("users.show.nope");
  });
});

describe("ICU messages", () => {
  const source = createTranslator({ locale: "en", messages: SOURCE_MESSAGES });

  it("pluralise by the message, not by string concatenation", () => {
    expect(source("shells.form.fieldsNeedAttention", { count: 1 })).toBe("1 field needs attention.");
    expect(source("shells.form.fieldsNeedAttention", { count: 3 })).toBe("3 fields need attention.");
    expect(source("users.sessions.signedOut", { count: 1 })).toBe("Signed out of 1 session.");
    expect(source("users.sessions.signedOut", { count: 0 })).toBe("Signed out of 0 sessions.");
  });

  it("group numbers by the reader's locale", () => {
    const de = createTranslator({ locale: "de-DE", messages: SOURCE_MESSAGES });
    expect(de("dataTable.bulk.selected", { count: 1234 })).toBe("1.234 selected");
    const inr = createTranslator({ locale: "en-IN", messages: SOURCE_MESSAGES });
    expect(inr("dataTable.pager.range", { from: 1, to: 25, count: 1234567, noun: "rows" })).toBe("1–25 of 12,34,567 rows");
  });

  it("use the translation's plural forms, and the source copy for keys it lacks", () => {
    const de = createTranslator({ locale: "de-DE", messages: mergeMessages(SOURCE_MESSAGES, PARTIAL) });
    expect(de("shells.form.fieldsNeedAttention", { count: 1 })).toBe("1 Feld prüfen.");
    expect(de("shells.form.fieldsNeedAttention", { count: 2 })).toBe("2 Felder prüfen.");
    expect(de("shells.form.save")).toBe("Save changes");
  });
});

function Probe() {
  const t = useT("dataTable.bulk");
  return <p>{t("selected", { count: 1234 })}</p>;
}

function renderInApp() {
  const client = makeQueryClient();
  client.setDefaultOptions({ queries: { ...client.getDefaultOptions().queries, retry: false } });
  return render(
    <QueryClientProvider client={client}>
      <LocalizationProvider platform={{ locale: "en-IN", timezone: "Asia/Kolkata" }}>
        <I18nProvider>
          <Probe />
        </I18nProvider>
      </LocalizationProvider>
    </QueryClientProvider>,
  );
}

describe("<I18nProvider>", () => {
  it("translates in the signed-in viewer's locale, from bootstrap", async () => {
    server.use(
      http.get(BOOT, () =>
        HttpResponse.json({
          user: {}, permissions: [], session: {}, server_time: "x", degraded: [],
          localization: { locale: "de-DE", timezone: "Europe/Berlin", currency: "EUR", country: "DE", date_style: "locale", time_style: "locale", week_start: "locale" },
        }),
      ),
    );
    renderInApp();
    expect(await screen.findByText("1.234 selected")).toBeInTheDocument();
  });

  it("falls back to the platform's locale while signed out", async () => {
    server.use(http.get(BOOT, () => HttpResponse.json({ error: { code: "not_authenticated", message: "x" } }, { status: 401 })));
    server.use(http.post(`${API_URL}/api/auth/refresh/`, () => new HttpResponse(null, { status: 401 })));
    renderInApp();
    expect(await screen.findByText("1,234 selected")).toBeInTheDocument();
  });

  it("warns about a missing key in development and renders its path, never throwing", () => {
    server.use(http.get(BOOT, () => HttpResponse.json({ error: { code: "not_authenticated", message: "x" } }, { status: 401 })));
    server.use(http.post(`${API_URL}/api/auth/refresh/`, () => new HttpResponse(null, { status: 401 })));
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    function Missing() {
      const t = useT("dataTable.bulk") as unknown as (key: string) => string;
      return <p>{t("nope")}</p>;
    }
    const client = makeQueryClient();
    render(
      <QueryClientProvider client={client}>
        <LocalizationProvider platform={{ locale: "en", timezone: "UTC" }}>
          <I18nProvider>
            <Missing />
          </I18nProvider>
        </LocalizationProvider>
      </QueryClientProvider>,
    );
    expect(screen.getByText("dataTable.bulk.nope")).toBeInTheDocument();
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });
});
