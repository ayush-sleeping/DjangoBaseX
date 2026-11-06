/**
 * The full, unfiltered navigation manifest, generated from the backend registry
 * (backend/tests/test_navigation.py writes and checks src/generated/nav-manifest.json). It holds
 * the boilerplate's own pages; a linked plugin's entries arrive per user in bootstrap's `nav`.
 *
 * Read by the proxy (which pages are public) and the route gate (which entry owns a page, before
 * the user's permissions are applied). It is data, not a decision: the API still decides.
 */
import generated from "@/generated/nav-manifest.json";

import { flatten, type NavSection, type RouteEntry } from "./resolve-route";

export const NAV_MANIFEST: readonly NavSection[] = (generated as { sections: NavSection[] }).sections;
export const MANIFEST_ENTRIES: readonly RouteEntry[] = flatten(NAV_MANIFEST);
