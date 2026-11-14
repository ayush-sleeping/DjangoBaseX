/**
 * This plugin's copy, added to the platform's typed catalogue (FRONTEND_PLATFORM § 22, BUILD_ORDER
 * 8.4d). Its catalogues hold one top-level key, the plugin's name, so `useT("enquiries")` typechecks
 * while the plugin is linked and a misspelt key does not. Same pattern as permissions.ts.
 */
import type en from "./messages/en.json";

declare module "@/core/lib/i18n" {
  interface PluginMessages {
    enquiries: (typeof en)["enquiries"];
  }
}
