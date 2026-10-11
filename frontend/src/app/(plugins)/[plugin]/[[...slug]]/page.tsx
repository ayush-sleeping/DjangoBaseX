import { notFound } from "next/navigation";

import { resolvePluginPage } from "@/core/lib/plugin-pages";
import { plugins } from "@/plugins/registry.generated";

// The one route every plugin page mounts through (CORE_ARCHITECTURE_PLAN § 5). Static routes win
// over this dynamic one, so a plugin can never shadow a core page; anything no plugin claims 404s.
// params is async in Next 16.
export default async function PluginRoute({ params }: PageProps<"/[plugin]/[[...slug]]">) {
  const { plugin, slug } = await params;
  const load = resolvePluginPage(plugins, plugin, slug);
  if (!load) notFound();
  const { default: Page } = await load();
  return <Page />;
}
