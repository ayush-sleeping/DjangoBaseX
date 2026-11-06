"use client";

/**
 * The client half of the plugin layout: looks the plugin up in the generated registry and mounts its
 * catalogue through core's ExtendMessages. Lives under src/app because core never imports a plugin
 * (CORE_ARCHITECTURE_PLAN § 6); the registry is read only here and by the catch-all page.
 */
import type { ReactNode } from "react";

import { ExtendMessages } from "@/core/lib/i18n";
import { plugins } from "@/plugins/registry.generated";

export function PluginCatalogue({ prefix, children }: { prefix: string; children: ReactNode }) {
  const mounted = Object.hasOwn(plugins, prefix) ? plugins[prefix] : undefined;
  // No plugin under this prefix: the page itself answers 404; nothing to mount.
  if (!mounted) return <>{children}</>;
  return (
    <ExtendMessages namespace={mounted.name} catalogues={mounted.messages}>
      {children}
    </ExtendMessages>
  );
}
