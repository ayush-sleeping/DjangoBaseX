/**
 * Translation for client components (FRONTEND_PLATFORM § 22, BUILD_ORDER 8.4c).
 *
 *   const t = useT("users.show");
 *   t("activateTitle", { name })          // ICU: {name}, {count, plural, …}, {n, number}
 *   t.rich("expires", { date: () => <DateTime value={…} /> })
 *
 * This directory is the only importer of next-intl (lint). Keys are typed from en.json, so an unknown
 * key or namespace is a compile error; messages.test.ts also fails on any en.json key nothing uses.
 * Call useT with a string literal and pass string literal keys: the test reads them statically.
 *
 * Server components use getServerT() from ./server instead: next-intl's server hooks need its plugin.
 */
import { useTranslations } from "next-intl";

import type { Messages } from "./messages";

declare module "next-intl" {
  interface AppConfig {
    Messages: Messages;
  }
}

export const useT = useTranslations;

export { I18nProvider } from "./I18nProvider";
export { SOURCE_LOCALE, type Messages } from "./messages";
