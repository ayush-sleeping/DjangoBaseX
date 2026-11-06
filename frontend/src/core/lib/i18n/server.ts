/**
 * Translation in server components (FRONTEND_PLATFORM § 22, BUILD_ORDER 8.4c): page titles,
 * metadata and signed-out pages.
 *
 *   export async function generateMetadata(): Promise<Metadata> {
 *     const t = await getServerT("users.index");
 *     return { title: t("title") };
 *   }
 *
 * next-intl's createTranslator is a pure function of {locale, messages}: no plugin, no request
 * config. The locale is the PLATFORM's (public config, cached a minute): a page request does not carry
 * the API session cookie, so the server cannot know the viewer's own locale without a locale cookie
 * that would make every route dynamic (§ 22 "As built"). Client components follow the viewer's.
 */
import { createTranslator, type NamespaceKeys, type NestedKeyOf } from "next-intl";

import { getIdentity } from "@/core/lib/identity";

import { loadMessages, type Messages, missingMessage } from "./messages";

export type Namespace = NamespaceKeys<Messages, NestedKeyOf<Messages>>;

export async function getServerT<const NS extends Namespace>(namespace: NS) {
  const { locale, timezone } = await getIdentity();
  const messages = await loadMessages(locale);
  return createTranslator({
    locale,
    timeZone: timezone,
    messages,
    namespace,
    onError: () => undefined, // a missing key renders its path (below); never fail a render
    getMessageFallback: missingMessage,
  });
}
