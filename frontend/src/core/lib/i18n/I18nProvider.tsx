"use client";

/**
 * The translation provider (FRONTEND_PLATFORM § 22, BUILD_ORDER 8.4c): next-intl's client provider,
 * fed by the SAME locale and zone as the formatters (useLocalization: bootstrap → platform →
 * shipped), so copy and numbers never disagree about who is reading.
 *
 * Client-side only, with no next-intl plugin: the source catalogue is bundled and renders at once;
 * another language's catalogue loads lazily and replaces it key by key (messages.ts). Server
 * components translate with getServerT() (./server.ts), never with next-intl's server hooks, which
 * need the plugin's request config.
 */
import { NextIntlClientProvider } from "next-intl";
import { type ReactNode, useEffect, useState } from "react";

import { useLocalization } from "@/core/lib/format/use-format";

import { catalogueFor, loadMessages, type Messages, missingMessage, SOURCE_MESSAGES } from "./messages";

function reportMissing(error: { code: string; message: string }) {
  // A missing key renders its path (getMessageFallback); say so in development, never throw.
  if (process.env.NODE_ENV !== "production") console.warn(`i18n: ${error.code}: ${error.message}`);
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const { locale, timezone } = useLocalization();
  const tag = catalogueFor(locale);
  const [loaded, setLoaded] = useState<{ tag: string; messages: Messages } | null>(null);

  useEffect(() => {
    if (!tag) return;
    let live = true;
    void loadMessages(locale).then((messages) => {
      if (live) setLoaded({ tag, messages });
    });
    return () => {
      live = false;
    };
  }, [locale, tag]);

  // Until a lazily loaded catalogue arrives, the source copy shows (never an empty screen).
  const messages = tag && loaded?.tag === tag ? loaded.messages : SOURCE_MESSAGES;
  return (
    <NextIntlClientProvider
      locale={locale}
      timeZone={timezone}
      messages={messages}
      onError={reportMissing}
      getMessageFallback={missingMessage}
    >
      {children}
    </NextIntlClientProvider>
  );
}
