"use client";

/**
 * A plugin's catalogue, mounted under its NAME inside the app's messages (BUILD_ORDER 8.4d).
 *
 * Core never imports a plugin: the (plugins) route hands this the plugin's name and its catalogue
 * loaders from the generated registry. Inside, every core key still resolves (the parent's messages
 * are kept), and the plugin's own keys are added under `namespace` only:
 *
 * - its lane: a top-level key other than `namespace` in a plugin catalogue is DROPPED (and warned
 *   about); plugin-messages.test.ts refuses it before it ships;
 * - its name: a namespace that ALREADY exists in the app's messages (a plugin named "theme") is
 *   refused at runtime too — the page renders with the app's messages unchanged and development
 *   warns — so a plugin can never replace core's copy, even if the backend's reserved-label check
 *   and the lane test were bypassed;
 * - its fallback, key by key: the plugin's catalogues for the viewer's locale, least specific first
 *   ("de", then "de-AT", when both ship), over the plugin's source catalogue (`en`), then the key
 *   path. Never core's copy.
 *
 * Until the catalogue has loaded, nothing renders: a page of raw key paths is worse than a beat of
 * blank. If it cannot load, the page renders anyway, with key paths, and development warns.
 */
import { NextIntlClientProvider, useLocale, useMessages, useTimeZone } from "next-intl";
import { type ReactNode, useEffect, useState } from "react";

import { type CatalogueLoaders, catalogueModule, loadOver, missingMessage, reportIntlError, SOURCE_LOCALE, type Tree, warnOnce } from "./messages";

/** The plugin's messages under `namespace` for `locale`, or null when it ships no usable source. */
export async function loadPluginMessages(namespace: string, locale: string, loaders: CatalogueLoaders): Promise<Tree | null> {
  const sourceLoader = loaders[SOURCE_LOCALE];
  if (!sourceLoader) {
    warnOnce(`plugin "${namespace}" ships catalogues but no "${SOURCE_LOCALE}" source catalogue`);
    return null;
  }
  const source = catalogueModule(await sourceLoader());
  const foreign = Object.keys(source).filter((key) => key !== namespace);
  if (foreign.length) warnOnce(`plugin "${namespace}" defines keys outside its namespace (${foreign.join(", ")}); they are ignored`);
  const own = source[namespace];
  if (!own || typeof own !== "object") {
    warnOnce(`plugin "${namespace}"'s source catalogue has no "${namespace}" namespace`);
    return null;
  }
  // Only the plugin's own namespace is the base, so a translation's foreign keys are dropped too.
  const merged = await loadOver({ [namespace]: own }, locale, loaders);
  return merged[namespace] as Tree;
}

export function ExtendMessages({
  namespace,
  catalogues,
  children,
}: {
  /** The plugin's name (its label): the one top-level key it owns. */
  namespace: string;
  /** Locale tag → lazy JSON, from the plugin's frontend package; undefined when it ships none. */
  catalogues: CatalogueLoaders | undefined;
  children: ReactNode;
}) {
  const locale = useLocale();
  const timeZone = useTimeZone();
  const parent = useMessages();
  const want = `${namespace}|${locale}`;
  const [loaded, setLoaded] = useState<{ want: string; tree: Tree | null } | null>(null);
  // Core's (or another provider's) namespace: never replaced by a plugin's catalogue.
  const taken = Object.hasOwn(parent, namespace);

  useEffect(() => {
    if (!catalogues || taken) return;
    let live = true;
    loadPluginMessages(namespace, locale, catalogues).then(
      (tree) => live && setLoaded({ want, tree }),
      () => {
        warnOnce(`plugin "${namespace}"'s catalogue could not be loaded`);
        if (live) setLoaded({ want, tree: null });
      },
    );
    return () => {
      live = false;
    };
  }, [namespace, locale, catalogues, want, taken]);

  if (taken) {
    warnOnce(`plugin "${namespace}" takes a namespace the app already has; its catalogue is ignored`);
    return <>{children}</>;
  }
  if (!catalogues) return <>{children}</>;
  if (loaded?.want !== want) return null;
  const messages = loaded.tree ? { ...parent, [namespace]: loaded.tree } : parent;
  return (
    <NextIntlClientProvider
      locale={locale}
      timeZone={timeZone}
      messages={messages}
      onError={reportIntlError}
      getMessageFallback={missingMessage}
    >
      {children}
    </NextIntlClientProvider>
  );
}
