/**
 * This plugin's copy, added to the platform's typed catalogue (FRONTEND_PLATFORM § 22, BUILD_ORDER
 * 8.4d). Its catalogues hold one top-level key, the plugin's name, so `useT("notes")` typechecks
 * while the plugin is linked and a misspelt key does not. Same pattern as permissions.ts.
 *
 * messages/de.json is deliberately partial: German readers see its two keys and the English source
 * for the rest, key by key.
 */
import type en from "./messages/en.json";

declare module "@/core/lib/i18n" {
  interface PluginMessages {
    notes: (typeof en)["notes"];
  }
}
