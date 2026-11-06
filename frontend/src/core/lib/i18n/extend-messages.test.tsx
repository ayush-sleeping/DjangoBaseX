/**
 * A plugin's catalogue inside the app's (BUILD_ORDER 8.4d): mounted under its name only, with the
 * per-key fallback translation → plugin source → key path, core's keys untouched.
 */
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ExtendMessages, useT } from "./index";
import { resetWarnings, SOURCE_MESSAGES } from "./messages";

afterEach(() => {
  resetWarnings();
  vi.restoreAllMocks();
});

const NOTES_EN = {
  notes: { title: "Notes", body: "Note", count: "{count, plural, one {# note} other {# notes}}" },
  // Out of lane: must be dropped, never overriding core's users.* copy.
  users: { index: { title: "Hijacked" } },
};
const NOTES_DE = { notes: { title: "Notizen", body: "{kaputt" } };

const loaders = {
  en: async () => ({ default: NOTES_EN }),
  de: async () => ({ default: NOTES_DE }),
};

function Probe() {
  const t = useT() as unknown as (key: string, values?: Record<string, unknown>) => string;
  return (
    <ul>
      <li>{t("notes.title")}</li>
      <li>{t("notes.body")}</li>
      <li>{t("notes.count", { count: 1234 })}</li>
      <li>{t("common.cancel")}</li>
      <li>{t("users.index.title")}</li>
    </ul>
  );
}

function inLocale(locale: string, ui: ReactNode) {
  return (
    <NextIntlClientProvider locale={locale} timeZone="UTC" messages={SOURCE_MESSAGES}>
      {ui}
    </NextIntlClientProvider>
  );
}

describe("<ExtendMessages>", () => {
  it("mounts the translation over the plugin's source, key by key, and keeps core's keys", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    render(inLocale("de-DE", <ExtendMessages namespace="notes" catalogues={loaders}><Probe /></ExtendMessages>));
    expect(await screen.findByText("Notizen")).toBeInTheDocument(); // translated
    expect(screen.getByText("Note")).toBeInTheDocument(); // malformed translation → the plugin's source
    expect(screen.getByText("1.234 notes")).toBeInTheDocument(); // untranslated → source, German digits
    expect(screen.getByText("Cancel")).toBeInTheDocument(); // core's copy still resolves
    expect(screen.getByText("Users")).toBeInTheDocument(); // the out-of-lane key was dropped
    expect(warn.mock.calls.map((c) => String(c[0])).join("\n")).toMatch(/outside its namespace \(users\)/);
  });

  it("renders nothing until the catalogue arrives (no flash of key paths)", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => (release = resolve));
    const slow = { en: async () => (await gate, { default: { notes: NOTES_EN.notes } }) };
    render(inLocale("en", <ExtendMessages namespace="notes" catalogues={slow}><Probe /></ExtendMessages>));
    expect(screen.queryByText("notes.title")).toBeNull();
    expect(screen.queryByText("Notes")).toBeNull();
    release();
    expect(await screen.findByText("Notes")).toBeInTheDocument();
  });

  it("renders the page, with key paths, when the catalogue cannot load", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const broken = { en: () => Promise.reject(new Error("chunk")) };
    render(inLocale("en", <ExtendMessages namespace="notes" catalogues={broken}><Probe /></ExtendMessages>));
    expect(await screen.findByText("notes.title")).toBeInTheDocument();
    expect(screen.getByText("Cancel")).toBeInTheDocument();
  });

  it("refuses a plugin whose name is already one of the app's namespaces, leaving core's copy intact", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const hijack = { en: async () => ({ default: { theme: { light: "HIJACKED" } } }) };
    function Theme() {
      const t = useT("theme");
      return <p>{t("light")}</p>;
    }
    render(inLocale("en", <ExtendMessages namespace="theme" catalogues={hijack}><Theme /></ExtendMessages>));
    expect(screen.getByText("Light")).toBeInTheDocument(); // rendered at once, with core's copy
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByText("HIJACKED")).toBeNull();
    expect(warn.mock.calls.map((c) => String(c[0])).join("\n")).toMatch(/plugin "theme" takes a namespace the app already has/);
  });

  it("layers a regional catalogue over its language, over the source", async () => {
    const layered = {
      en: async () => ({ default: { notes: NOTES_EN.notes } }),
      de: async () => ({ default: { notes: { title: "Notizen", body: "Notiz" } } }),
      "de-AT": async () => ({ default: { notes: { title: "Notizen (AT)" } } }),
    };
    render(inLocale("de-AT", <ExtendMessages namespace="notes" catalogues={layered}><Probe /></ExtendMessages>));
    expect(await screen.findByText("Notizen (AT)")).toBeInTheDocument(); // de-AT
    expect(screen.getByText("Notiz")).toBeInTheDocument(); // de, beneath it
    // The source, beneath both (grouped the Austrian way, with a narrow space).
    expect(screen.getByText(/^1\D234 notes$/)).toBeInTheDocument();
  });

  it("is a no-op for a plugin that ships no catalogue", () => {
    render(inLocale("en", <ExtendMessages namespace="notes" catalogues={undefined}><p>plain</p></ExtendMessages>));
    expect(screen.getByText("plain")).toBeInTheDocument();
  });
});
