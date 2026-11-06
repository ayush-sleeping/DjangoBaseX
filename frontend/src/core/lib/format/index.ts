/**
 * The ONE place a number, amount, size or date becomes text (FRONTEND_PLATFORM § 14, BUILD_ORDER
 * 8.4b). ESLint refuses toLocale*(), new Intl.*Format and any format* declaration anywhere else.
 *
 * No literal locale, timezone or currency lives here or anywhere in the frontend: every function
 * takes a Localization — the viewer's, from bootstrap; the platform's, from public config; or, as a
 * last resort, the backend's shipped defaults (src/generated/localization.ts). A German ERP in EUR, a
 * shop in INR and a CRM in en-US run the same code.
 *
 * - A date-only value ("2026-03-01") is a calendar date: it is never passed through a timezone, so
 *   it cannot render as 28 February west of Greenwich.
 * - A datetime is ISO-8601 UTC from the API and is always formatted with an EXPLICIT timeZone, so
 *   the server and the browser agree and hydration never mismatches.
 * - Money is a decimal STRING plus an ISO-4217 code. It is never parsed into a float: Intl formats
 *   the string exactly. An unknown or missing code renders the code (or "¤") and the number and
 *   warns in development — it never throws RangeError and never assumes a currency. There is no
 *   symbol table: Intl owns symbols.
 */
import { format as formatDefaults } from "@/core/lib/config/defaults";
import { SHIPPED_LOCALIZATION } from "@/generated/localization";

export type Style = "locale" | "short" | "medium" | "long";

/** The viewer's resolved formats (bootstrap `localization`; the same keys as LocalePolicy). */
export type Localization = {
  locale: string;
  timezone: string;
  currency: string | null;
  country: string | null;
  date_style: string;
  time_style: string;
  week_start: string;
};

/** The backend's shipped defaults: only for when nothing has been resolved yet. */
export const FALLBACK_LOCALIZATION: Localization = { ...SHIPPED_LOCALIZATION };

export const EMPTY = formatDefaults.emptyValue;

type Empty = null | undefined | "";
const isEmpty = (value: unknown): value is Empty => value === null || value === undefined || value === "";

/** "locale" means: the locale's own conventions, at medium length. */
function intlStyle(style: string): "short" | "medium" | "long" {
  return style === "short" || style === "long" ? style : "medium";
}

function warnOnce(key: string, message: string): void {
  if (process.env.NODE_ENV === "production") return;
  const seen = (globalThis as { __dbxFormatWarned?: Set<string> }).__dbxFormatWarned ?? new Set<string>();
  (globalThis as { __dbxFormatWarned?: Set<string> }).__dbxFormatWarned = seen;
  if (seen.has(key)) return;
  seen.add(key);
  console.warn(message);
}

/** A decimal string or number, as Intl takes it: strings stay exact. */
type Numeric = number | `${number}`;
const DECIMAL = /^[+-]?(\d+(\.\d*)?|\.\d+)$/;

function asNumeric(value: number | string): Numeric | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  const trimmed = value.trim();
  return DECIMAL.test(trimmed) ? (trimmed as `${number}`) : null;
}

export function formatNumber(value: number | string | Empty, loc: Localization, options: Intl.NumberFormatOptions = {}): string {
  if (isEmpty(value)) return EMPTY;
  const numeric = asNumeric(value);
  if (numeric === null) return EMPTY;
  return new Intl.NumberFormat(loc.locale, options).format(numeric);
}

/** A ratio (0.25) as a percentage ("25%"). */
export function formatPercent(ratio: number | string | Empty, loc: Localization, maximumFractionDigits = 1): string {
  return formatNumber(ratio, loc, { style: "percent", maximumFractionDigits });
}

function validCurrency(code: string | null | undefined, locale: string): code is string {
  if (!code || !/^[A-Z]{3}$/.test(code)) return false;
  try {
    new Intl.NumberFormat(locale, { style: "currency", currency: code });
    return Intl.supportedValuesOf ? Intl.supportedValuesOf("currency").includes(code) : true;
  } catch {
    return false;
  }
}

/**
 * An amount in its currency. `amount` is the API's decimal string (never a float); `currency` is the
 * record's ISO code, not the viewer's preference — a USD invoice stays in USD for a EUR viewer.
 */
export function formatMoney(amount: string | number | Empty, currency: string | null | undefined, loc: Localization): string {
  if (isEmpty(amount)) return EMPTY;
  const numeric = asNumeric(amount);
  if (numeric === null) return EMPTY;
  if (!validCurrency(currency, loc.locale)) {
    warnOnce(`currency:${currency}`, `formatMoney: unknown currency ${JSON.stringify(currency)}; rendering the bare amount.`);
    const plain = new Intl.NumberFormat(loc.locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(numeric);
    return `${currency || "¤"} ${plain}`;
  }
  return new Intl.NumberFormat(loc.locale, { style: "currency", currency }).format(numeric);
}

const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;

/**
 * A calendar date ("2026-03-01"). Built as that day in UTC and formatted in UTC, so no zone can
 * move it to another day.
 */
export function formatDate(value: string | Empty, loc: Localization): string {
  if (isEmpty(value)) return EMPTY;
  const match = DATE_ONLY.exec(value);
  if (!match) return EMPTY;
  const [, y, m, d] = match;
  const day = new Date(Date.UTC(Number(y), Number(m) - 1, Number(d)));
  return new Intl.DateTimeFormat(loc.locale, { dateStyle: intlStyle(loc.date_style), timeZone: "UTC" }).format(day);
}

/** An instant (ISO-8601 from the API) in the viewer's zone, with that zone passed explicitly. */
export function formatDateTime(value: string | Empty, loc: Localization): string {
  if (isEmpty(value)) return EMPTY;
  const instant = new Date(value);
  if (Number.isNaN(instant.getTime())) return EMPTY;
  return new Intl.DateTimeFormat(loc.locale, {
    dateStyle: intlStyle(loc.date_style),
    timeStyle: intlStyle(loc.time_style) === "long" ? "medium" : "short",
    timeZone: loc.timezone,
  }).format(instant);
}

/** The same instant in UTC with the zone named: the tooltip under every <DateTime>. */
export function formatInstantUtc(value: string | Empty, loc: Localization): string {
  if (isEmpty(value)) return EMPTY;
  const instant = new Date(value);
  if (Number.isNaN(instant.getTime())) return EMPTY;
  const utc = new Intl.DateTimeFormat(loc.locale, { dateStyle: "medium", timeStyle: "medium", timeZone: "UTC" }).format(instant);
  return `${utc} UTC · shown in ${loc.timezone}`;
}

const UNITS = { 1024: ["B", "KiB", "MiB", "GiB", "TiB", "PiB"], 1000: ["B", "kB", "MB", "GB", "TB", "PB"] } as const;

/** A size in bytes, in one configured base with its own unit labels. */
export function formatBytes(bytes: number | Empty, loc: Localization, base: 1024 | 1000 = formatDefaults.bytesBase): string {
  if (isEmpty(bytes) || !Number.isFinite(bytes) || bytes < 0) return EMPTY;
  const units = UNITS[base];
  let value = bytes;
  let unit = 0;
  while (value >= base && unit < units.length - 1) {
    value /= base;
    unit += 1;
  }
  const number = new Intl.NumberFormat(loc.locale, { maximumFractionDigits: unit === 0 ? 0 : 1 }).format(value);
  return `${number} ${units[unit]}`;
}
