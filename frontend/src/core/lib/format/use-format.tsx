"use client";

/**
 * The viewer's formatters (FRONTEND_PLATFORM § 14). One answer to "which locale, which zone":
 *
 *   bootstrap `localization` (signed in: user → tenant → platform, resolved by the backend)
 *   → the platform's locale and timezone from /api/public/config/ (signed out; passed down from
 *     the root layout)
 *   → the backend's shipped defaults (src/generated/localization.ts), only until either arrives.
 */
import { createContext, type ReactNode, useContext, useMemo } from "react";

import { useBootstrap } from "@/core/lib/bootstrap";

import {
  FALLBACK_LOCALIZATION,
  formatBytes,
  formatDate,
  formatDateTime,
  formatInstantUtc,
  formatMoney,
  formatNumber,
  formatPercent,
  type Localization,
} from "./index";

/** The platform's locale and timezone, known to the root layout before anyone signs in. */
export type PlatformLocale = Pick<Localization, "locale" | "timezone">;

const PlatformCtx = createContext<PlatformLocale | null>(null);

export function LocalizationProvider({ platform, children }: { platform: PlatformLocale; children: ReactNode }) {
  return <PlatformCtx.Provider value={platform}>{children}</PlatformCtx.Provider>;
}

export function useLocalization(): Localization {
  const boot = useBootstrap();
  const platform = useContext(PlatformCtx);
  const resolved = boot.data?.localization;
  return useMemo(
    () => resolved ?? { ...FALLBACK_LOCALIZATION, ...(platform ?? {}) },
    [resolved, platform],
  );
}

/** The formatters, bound to the viewer's localization. */
export function useFormat() {
  const loc = useLocalization();
  return useMemo(
    () => ({
      localization: loc,
      number: (value: number | string | null | undefined, options?: Intl.NumberFormatOptions) => formatNumber(value, loc, options),
      percent: (ratio: number | string | null | undefined, digits?: number) => formatPercent(ratio, loc, digits),
      money: (amount: string | number | null | undefined, currency: string | null | undefined) => formatMoney(amount, currency, loc),
      date: (value: string | null | undefined) => formatDate(value, loc),
      dateTime: (value: string | null | undefined) => formatDateTime(value, loc),
      instantUtc: (value: string | null | undefined) => formatInstantUtc(value, loc),
      bytes: (value: number | null | undefined) => formatBytes(value, loc),
    }),
    [loc],
  );
}
