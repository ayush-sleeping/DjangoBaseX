// @vitest-environment node
/**
 * The one formatting home (FRONTEND_PLATFORM § 14, BUILD_ORDER 8.4b), under SEVERAL process
 * timezones: Node re-reads process.env.TZ at runtime, so each case runs with the machine's zone
 * changed underneath it — and must not change its answer. A positive control proves the switch
 * really moves the process zone, so the test cannot pass vacuously.
 *
 * Markets: a German ERP in EUR, a shop in INR, a CRM in en-US — none of them is a default.
 */
import { afterAll, describe, expect, it, vi } from "vitest";

import { EMPTY, formatBytes, formatDate, formatDateTime, formatMoney, formatNumber, formatPercent, type Localization } from "./index";

const ORIGINAL_TZ = process.env.TZ;
afterAll(() => {
  process.env.TZ = ORIGINAL_TZ;
});

const base = { country: null, currency: null, date_style: "locale", time_style: "locale", week_start: "locale" };
const DE: Localization = { ...base, locale: "de-DE", timezone: "Europe/Berlin" };
const IN: Localization = { ...base, locale: "en-IN", timezone: "Asia/Kolkata" };
const US: Localization = { ...base, locale: "en-US", timezone: "America/New_York" };

// The process zones the machine might run in: west and east of Greenwich, and UTC.
const PROCESS_ZONES = ["UTC", "Pacific/Kiritimati", "Pacific/Pago_Pago"];

/** What each formatter answers for fixed inputs, in one process zone. */
function snapshot(): Record<string, string> {
  return {
    dateDe: formatDate("2026-03-01", DE),
    dateUs: formatDate("2026-03-01", US),
    dateTimeUs: formatDateTime("2026-03-01T03:30:00Z", US),
    dateTimeIn: formatDateTime("2026-03-01T03:30:00Z", IN),
    moneyDe: formatMoney("1234567.5", "EUR", DE),
    moneyIn: formatMoney("1234567.5", "INR", IN),
    moneyUs: formatMoney("1234567.5", "USD", US),
  };
}

describe("formatters do not depend on the machine's timezone", () => {
  it("the positive control: changing process.env.TZ really moves the process zone", () => {
    process.env.TZ = "Pacific/Kiritimati";
    const east = new Date(2026, 2, 1).getTimezoneOffset();
    process.env.TZ = "Pacific/Pago_Pago";
    const west = new Date(2026, 2, 1).getTimezoneOffset();
    expect(east).not.toBe(west);
  });

  it("gives the same answers in every process zone", () => {
    const answers = PROCESS_ZONES.map((zone) => {
      process.env.TZ = zone;
      return snapshot();
    });
    for (const answer of answers.slice(1)) expect(answer).toEqual(answers[0]);
  });

  it.each(PROCESS_ZONES)("never shifts a date-only value (process zone %s)", (zone) => {
    process.env.TZ = zone;
    expect(formatDate("2026-03-01", US)).toMatch(/Mar 1, 2026/);
    expect(formatDate("2026-03-01", DE)).toMatch(/1\. März 2026|01\.03\.2026/);
  });
});

describe("dates and times", () => {
  it("formats an instant in the VIEWER's zone, passed explicitly", () => {
    // 03:30 UTC on 1 March is 22:30 on 28 February in New York, and 09:00 on 1 March in Kolkata.
    expect(formatDateTime("2026-03-01T03:30:00Z", US)).toMatch(/Feb 28, 2026/);
    expect(formatDateTime("2026-03-01T03:30:00Z", IN)).toMatch(/1 Mar 2026/);
  });

  it("renders the one empty marker for missing or malformed values", () => {
    for (const value of [null, undefined, "", "not-a-date"]) expect(formatDateTime(value, US)).toBe(EMPTY);
    for (const value of [null, "2026-3-1", "01/03/2026"]) expect(formatDate(value, US)).toBe(EMPTY);
  });
});

describe("money", () => {
  it("formats each market's amounts in its own conventions", () => {
    expect(formatMoney("1234567.5", "EUR", DE)).toBe("1.234.567,50 €");
    expect(formatMoney("1234567.5", "INR", IN)).toBe("₹12,34,567.50");
    expect(formatMoney("1234567.5", "USD", US)).toBe("$1,234,567.50");
  });

  it("keeps the record's currency whatever the viewer's market", () => {
    expect(formatMoney("10", "USD", DE)).toBe("10,00 $");
  });

  it("formats a decimal string exactly, beyond float precision", () => {
    expect(formatMoney("12345678901234567.89", "EUR", DE)).toBe("12.345.678.901.234.567,89 €");
  });

  it("never throws on an unknown or missing currency, and never assumes one", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    expect(formatMoney("12.5", "XYZ", US)).toBe("XYZ 12.50");
    expect(formatMoney("12.5", null, DE)).toBe("¤ 12,50");
    expect(formatMoney("12.5", "eur", US)).toBe("eur 12.50");
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });

  it("renders the empty marker for a missing or non-numeric amount", () => {
    expect(formatMoney(null, "EUR", DE)).toBe(EMPTY);
    expect(formatMoney("12,5", "EUR", DE)).toBe(EMPTY); // the API sends "12.5"; a localised string is a bug upstream
  });
});

describe("numbers and sizes", () => {
  it("groups by the locale", () => {
    expect(formatNumber(1234567, IN)).toBe("12,34,567");
    expect(formatNumber("1234567.25", DE)).toBe("1.234.567,25");
    expect(formatPercent(0.255, US)).toBe("25.5%");
  });

  it("uses one byte base with matching units", () => {
    expect(formatBytes(1536, US)).toBe("1.5 KiB");
    expect(formatBytes(1500, US, 1000)).toBe("1.5 kB");
    expect(formatBytes(-1, US)).toBe(EMPTY);
  });
});
