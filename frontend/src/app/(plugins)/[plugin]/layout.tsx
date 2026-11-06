import { PluginCatalogue } from "./plugin-catalogue";

/**
 * Every page of one plugin renders inside that plugin's catalogue (FRONTEND_PLATFORM § 22, BUILD_ORDER
 * 8.4d). The URL segment is the plugin's frontend PREFIX; the catalogue is keyed by its NAME, so a
 * product can move a plugin's URL without breaking its copy. params is async in Next 16.
 */
export default async function PluginLayout({ children, params }: LayoutProps<"/[plugin]">) {
  const { plugin } = await params;
  return <PluginCatalogue prefix={plugin}>{children}</PluginCatalogue>;
}
