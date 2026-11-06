/**
 * The message catalogues (FRONTEND_PLATFORM § 22, BUILD_ORDER 8.4c).
 *
 * `en` is the SOURCE catalogue: the language the copy is written in, always complete, always
 * bundled. It is not a default locale — the viewer's locale comes from bootstrap or the platform
 * (§ 14) — it is what a missing translation falls back to, KEY BY KEY: a half-translated catalogue
 * shows the translated keys and the source copy for the rest, never a raw key path.
 *
 * Another language is a JSON file beside en.json and one line in CATALOGUES, loaded lazily so the
 * bundle carries only the source catalogue. ICU messages only: no concatenation, no manual plurals.
 */
import source from "@/core/messages/en.json";

export type Messages = typeof source;
type Tree = { [key: string]: string | Tree };

/** The language the source copy is written in (the catalogue every other one falls back to). */
export const SOURCE_LOCALE = "en";
export const SOURCE_MESSAGES: Messages = source;

/** Translations other than the source, by BCP 47 tag ("de", "pt-BR"), loaded on demand. */
export const CATALOGUES: Readonly<Record<string, () => Promise<Partial<Messages>>>> = {};

/** The catalogue tags to try for a locale, most specific first: "de-AT" → ["de-AT", "de"]. */
export function candidates(locale: string): string[] {
  const parts = locale.split("-");
  const out: string[] = [];
  for (let n = parts.length; n > 0; n -= 1) out.push(parts.slice(0, n).join("-"));
  return out;
}

/** The best catalogue for a locale, or null when only the source applies. */
export function catalogueFor(locale: string, catalogues = CATALOGUES): string | null {
  if (candidates(locale).includes(SOURCE_LOCALE)) return null;
  return candidates(locale).find((tag) => Object.hasOwn(catalogues, tag)) ?? null;
}

/** `over` on top of `base`, key by key: whatever `over` lacks keeps the base's copy. */
export function mergeMessages<T extends Tree>(base: T, over: Partial<T> | Tree | undefined): T {
  if (!over) return base;
  const out: Tree = { ...base };
  for (const [key, value] of Object.entries(over)) {
    const current = out[key];
    if (typeof value === "string") {
      if (typeof current === "string") out[key] = value; // a key the source no longer has is dropped
    } else if (current && typeof current === "object") {
      out[key] = mergeMessages(current, value);
    }
  }
  return out as T;
}

/** The messages for a locale: its catalogue merged over the source. Never throws. */
export async function loadMessages(locale: string, catalogues = CATALOGUES): Promise<Messages> {
  const tag = catalogueFor(locale, catalogues);
  if (!tag) return SOURCE_MESSAGES;
  try {
    return mergeMessages(SOURCE_MESSAGES, await catalogues[tag]());
  } catch {
    return SOURCE_MESSAGES; // an unloadable catalogue shows the source copy, not a broken page
  }
}

/** What a key that is missing everywhere renders: its path, so the gap is visible and reportable. */
export function missingMessage({ namespace, key }: { namespace?: string; key: string }): string {
  return namespace ? `${namespace}.${key}` : key;
}
