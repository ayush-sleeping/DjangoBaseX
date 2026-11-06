/**
 * The translation context every rendered test gets (tests/setup.ts wraps render and renderHook in it):
 * the real next-intl provider with the real source catalogue — not a mock of t() — so a test asserts
 * the copy a user reads, and a broken key shows up as its path.
 *
 * Deliberately NOT the app's I18nProvider: that one reads bootstrap for the viewer's locale, and a
 * test that never asked for bootstrap must not fetch it (an unhandled MSW request fails the run).
 * The locale is the backend's shipped default, never a literal here.
 */
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";

import { missingMessage, SOURCE_MESSAGES } from "@/core/lib/i18n/messages";
import { SHIPPED_LOCALIZATION } from "@/generated/localization";

export function SourceIntl({ children }: { children: ReactNode }) {
  return (
    <NextIntlClientProvider
      locale={SHIPPED_LOCALIZATION.locale}
      timeZone={SHIPPED_LOCALIZATION.timezone}
      messages={SOURCE_MESSAGES}
      onError={(error) => {
        throw error; // a missing key in a test is a bug, not a fallback
      }}
      getMessageFallback={missingMessage}
    >
      {children}
    </NextIntlClientProvider>
  );
}
