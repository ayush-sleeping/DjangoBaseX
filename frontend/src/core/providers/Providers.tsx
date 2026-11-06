"use client";

/**
 * The root provider tree (FRONTEND_PLATFORM.md § 1), outermost first: the QueryClientProvider,
 * the LocalizationProvider (8.4b: the platform locale from the root layout, for formatters before
 * bootstrap and when signed out), the I18nProvider (8.4c: next-intl, on the same locale and zone),
 * the PermissionProvider (8.2, fed by bootstrap), and the one
 * ConfirmHost and Toaster (8.3a) that confirm() and toast() talk to. The identity and session
 * providers join as their tasks land, in the order § 1 fixes. The client is created once per
 * browser session in useState, never at module scope.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { ConfirmHost } from "@/core/components/confirm";
import { Toaster } from "@/core/components/toast";
import { LocalizationProvider, type PlatformLocale } from "@/core/lib/format/use-format";
import { I18nProvider } from "@/core/lib/i18n";
import { PermissionProvider } from "@/core/lib/permissions";
import { makeQueryClient } from "@/core/lib/query/client";
import { StatusProvider } from "@/core/lib/statuses";

export function Providers({ platform, children }: { platform: PlatformLocale; children: ReactNode }) {
  const [client] = useState(makeQueryClient);
  return (
    <QueryClientProvider client={client}>
      <LocalizationProvider platform={platform}>
        <I18nProvider>
          <PermissionProvider>
            <StatusProvider>{children}</StatusProvider>
          </PermissionProvider>
          <ConfirmHost />
          <Toaster />
        </I18nProvider>
      </LocalizationProvider>
    </QueryClientProvider>
  );
}
