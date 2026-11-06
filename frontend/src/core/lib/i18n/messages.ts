/**
 * The message catalogues (FRONTEND_PLATFORM § 22, BUILD_ORDER 8.4c, 8.4d).
 *
 * `en` is the SOURCE catalogue: the language the copy is written in, always complete, always
 * bundled. It is not a default locale — the viewer's locale comes from bootstrap or the platform
 * (§ 14) — it is what a missing or unusable translation falls back to, KEY BY KEY: a
 * half-translated catalogue shows the translated keys and the source copy for the rest.
 *
 * A translated string replaces the source only when it has the same SHAPE: balanced braces, the
 * same ICU arguments and rich-text tags, and an `other` branch in every plural/select. A translation
 * that drops {email} or breaks a plural keeps the source copy for that key (and warns once in
 * development), instead of rendering a broken string. Anything subtler, which only formatting
 * reveals, is caught by the test suite (validate.ts).
 *
 * Another language is a JSON file beside en.json and one line in CATALOGUES, loaded lazily so the
 * bundle carries only the source catalogue. ICU messages only: no concatenation, no manual plurals.
 */
import source from "@/core/messages/en.json";

export type Messages = typeof source;
export type Tree = { [key: string]: string | Tree };
export type CatalogueLoaders = Readonly<Record<string, () => Promise<unknown>>>;

/** The language the source copy is written in (the catalogue every other one falls back to). */
export const SOURCE_LOCALE = "en";
export const SOURCE_MESSAGES: Messages = source;

/** Translations other than the source, by BCP 47 tag ("de", "pt-BR"), loaded on demand. */
export const CATALOGUES: Readonly<Record<string, () => Promise<Partial<Messages>>>> = {};

// --- Development warnings, once per distinct message, shared by the client and the server ------

const warned = new Set<string>();

/** Warn in development, once per distinct text: a missing key renders on every frame otherwise. */
export function warnOnce(text: string): void {
  if (process.env.NODE_ENV === "production" || warned.has(text)) return;
  warned.add(text);
  console.warn(`i18n: ${text}`);
}

/** Tests only. */
export function resetWarnings(): void {
  warned.clear();
}

/** next-intl's onError: never throw, say so once (the key renders as its path). */
export function reportIntlError(error: { code: string; message: string }): void {
  warnOnce(`${error.code}: ${error.message}`);
}

// --- Catalogue resolution ----------------------------------------------------------------------

/** The catalogue tags to try for a locale, most specific first: "de-AT" → ["de-AT", "de"]. */
export function candidates(locale: string): string[] {
  const parts = locale.split("-");
  const out: string[] = [];
  for (let n = parts.length; n > 0; n -= 1) out.push(parts.slice(0, n).join("-"));
  return out;
}

/**
 * The catalogues that apply to a locale, LEAST specific first, so each is merged over the one before:
 * "de-AT" with both shipped → ["de", "de-AT"] (Austrian keys over German, German over the source).
 * Empty when the source language applies.
 */
export function cataloguesFor(locale: string, catalogues: CatalogueLoaders = CATALOGUES): string[] {
  const tags = candidates(locale);
  if (tags.includes(SOURCE_LOCALE)) return [];
  return tags.filter((tag) => Object.hasOwn(catalogues, tag)).reverse();
}

/** The most specific catalogue for a locale, or null when only the source applies. */
export function catalogueFor(locale: string, catalogues: CatalogueLoaders = CATALOGUES): string | null {
  return cataloguesFor(locale, catalogues).at(-1) ?? null;
}

// --- Message shape -----------------------------------------------------------------------------

const BRANCHING = new Set(["plural", "select", "selectordinal"]);

/**
 * What a message needs from its caller: its ICU arguments (with their type) and its rich-text tags,
 * as a sorted signature ("arg:count:plural|arg:name|tag:date"), or null when it does not parse (an
 * unbalanced brace, an unterminated branch). A small reader of the ICU subset the catalogues use:
 * {name}, {n, number}, {n, plural|select|selectordinal, key {…} …} and <tag></tag>.
 */
export function messageShape(text: string): string | null {
  const parts = new Set<string>();
  let i = 0;

  const fail = (): never => {
    throw new Error("malformed");
  };
  const readUntil = (stops: string): string => {
    const start = i;
    while (i < text.length && !stops.includes(text[i])) i += 1;
    if (i >= text.length) fail();
    return text.slice(start, i);
  };

  // Text until the closing brace of the enclosing branch (inBranch) or the end of the message.
  const readText = (inBranch: boolean): void => {
    while (i < text.length) {
      const ch = text[i];
      if (ch === "{") readArgument();
      else if (ch === "}") {
        if (!inBranch) fail();
        return;
      } else if (ch === "<") {
        const tag = /^<\/?([A-Za-z][\w-]*)>/.exec(text.slice(i));
        if (tag) {
          parts.add(`tag:${tag[1]}`);
          i += tag[0].length;
        } else i += 1;
      } else i += 1;
    }
    if (inBranch) fail();
  };

  const readArgument = (): void => {
    i += 1; // {
    const name = readUntil(",}").trim();
    if (!/^[A-Za-z_][\w]*$/.test(name)) fail();
    if (text[i] === "}") {
      parts.add(`arg:${name}`);
      i += 1;
      return;
    }
    i += 1; // ,
    const type = readUntil(",}").trim();
    parts.add(`arg:${name}:${type}`);
    if (text[i] === "}") {
      i += 1;
      return;
    }
    i += 1; // ,
    if (!BRANCHING.has(type)) {
      // A style ({n, number, ::percent}): skip it, braces balanced.
      let depth = 1;
      while (i < text.length && depth > 0) {
        if (text[i] === "{") depth += 1;
        else if (text[i] === "}") depth -= 1;
        i += 1;
      }
      if (depth !== 0) fail();
      return;
    }
    // Branches: `key {text}` pairs until the argument's own closing brace. ICU requires an `other`
    // branch: without one the message does not format, and the key would render as its path.
    const selectors: string[] = [];
    for (;;) {
      while (i < text.length && /\s/.test(text[i])) i += 1;
      if (text[i] === "}") {
        if (!selectors.includes("other")) fail();
        i += 1;
        return;
      }
      selectors.push(readUntil("{}").trim().split(/\s+/).pop() ?? "");
      if (text[i] === "}") fail(); // a selector with no branch
      i += 1; // {
      readText(true);
      i += 1; // }
    }
  };

  try {
    readText(false);
  } catch {
    return null;
  }
  return [...parts].sort().join("|");
}

/** Whether a translated string may stand in for the source string. */
export function sameShape(sourceText: string, translated: string): boolean {
  const expected = messageShape(sourceText);
  return expected !== null && messageShape(translated) === expected;
}

// --- Merging -----------------------------------------------------------------------------------

const UNSAFE_KEYS = new Set(["__proto__", "constructor", "prototype"]);

/**
 * `over` on top of `base`, key by key. Whatever `over` lacks keeps the base's copy; a key the base no
 * longer has is dropped; a translated string of a different shape keeps the base's copy and warns.
 */
export function mergeMessages<T extends Tree>(base: T, over: Partial<T> | Tree | undefined, path = ""): T {
  if (!over) return base;
  const out: Tree = { ...base };
  for (const [key, value] of Object.entries(over)) {
    // A catalogue is data from a file: a key that names the prototype chain is never a message.
    if (UNSAFE_KEYS.has(key) || !Object.hasOwn(out, key)) continue;
    const current = out[key];
    const where = path ? `${path}.${key}` : key;
    if (typeof value === "string") {
      if (typeof current !== "string") continue;
      if (sameShape(current, value)) out[key] = value;
      else warnOnce(`${where}: the translation's arguments or tags differ from the source, or it does not parse; showing the source copy`);
    } else if (current && typeof current === "object" && value && typeof value === "object") {
      out[key] = mergeMessages(current, value, where);
    }
  }
  return out as T;
}

/** A loaded catalogue: `() => import("./de.json")` resolves to a module whose default is the JSON. */
export function catalogueModule(loaded: unknown): Tree {
  const value = loaded && typeof loaded === "object" && "default" in loaded ? (loaded as { default: unknown }).default : loaded;
  return value && typeof value === "object" ? (value as Tree) : {};
}

/**
 * Every catalogue that applies to `locale`, merged over `base` least specific first ("de", then
 * "de-AT"), key by key. Never throws: a catalogue that cannot load is skipped, the rest still apply.
 */
export async function loadOver<T extends Tree>(base: T, locale: string, loaders: CatalogueLoaders): Promise<T> {
  let merged = base;
  for (const tag of cataloguesFor(locale, loaders)) {
    try {
      merged = mergeMessages(merged, catalogueModule(await loaders[tag]()));
    } catch {
      warnOnce(`the "${tag}" catalogue could not be loaded; showing the copy beneath it`);
    }
  }
  return merged;
}

/** The messages for a locale: its catalogue merged over the source. Never throws. */
export async function loadMessages(locale: string, catalogues: CatalogueLoaders = CATALOGUES): Promise<Messages> {
  return loadOver(SOURCE_MESSAGES, locale, catalogues);
}

/** What a key that is missing everywhere renders: its path, so the gap is visible and reportable. */
export function missingMessage({ namespace, key }: { namespace?: string; key: string }): string {
  return namespace ? `${namespace}.${key}` : key;
}
