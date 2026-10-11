/**
 * The frontend half of the plugin seam (CORE_ARCHITECTURE_PLAN § 5, BUILD_ORDER 3.5).
 *
 * A plugin's frontend/index.ts default-exports a PluginFrontend. scripts/plugins.py link symlinks
 * that directory to src/plugins/<prefix> and lists it in src/plugins/registry.generated.ts, and
 * one catch-all route, (plugins)/[plugin]/[[...slug]], resolves every plugin page through
 * resolvePluginPage(). Core never names a plugin: it reads the generated registry.
 */
import type { ComponentType } from "react";

/** A page module, loaded only when its URL is visited. */
export type PluginPage = () => Promise<{ default: ComponentType }>;

export type PluginFrontend = {
  /** The plugin's name, as in plugin.toml. */
  name: string;
  /** Sub-path under /<prefix>/ → page. "" is /<prefix> itself; "a/b" is /<prefix>/a/b. */
  pages: Record<string, PluginPage>;
};

/** The page for /<plugin>/<...slug>, or null (→ 404) when no plugin or page claims it. */
export function resolvePluginPage(
  plugins: Readonly<Record<string, PluginFrontend>>,
  plugin: string,
  slug: readonly string[] | undefined,
): PluginPage | null {
  const mounted = Object.hasOwn(plugins, plugin) ? plugins[plugin] : undefined;
  if (!mounted) return null;
  const key = (slug ?? []).join("/");
  return Object.hasOwn(mounted.pages, key) ? mounted.pages[key] : null;
}
