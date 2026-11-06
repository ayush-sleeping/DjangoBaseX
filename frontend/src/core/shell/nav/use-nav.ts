"use client";

/**
 * The menu this user may follow: bootstrap's `nav`, already filtered by the server on effective
 * permissions, minus the `hidden` entries that exist only for the route gate.
 */
import { useBootstrap } from "@/core/lib/bootstrap";

import type { NavSection } from "./resolve-route";

export function useNav() {
  const boot = useBootstrap();
  const sections: NavSection[] = (boot.data?.nav ?? [])
    .map((section) => ({ ...section, items: section.items.filter((item) => !item.hidden) }))
    .filter((section) => section.items.length > 0);
  // "nav" in degraded: the server could not build the menu — never render that as "no items".
  const degraded = boot.data?.degraded.includes("nav") ?? false;
  return { sections, isLoading: boot.isLoading, failed: boot.showError || degraded, signedIn: !!boot.data };
}
