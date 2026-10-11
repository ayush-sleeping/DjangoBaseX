/**
 * The menu the server built for this user (GET /api/me/navigation/, BUILD_ORDER 3.4 / 8.2).
 * Filtered on the server by effective permissions, so it lists only what the API will allow. It
 * still only shapes a menu: every endpoint decides for itself.
 */
import { api } from "./api";

export type NavItem = { key: string; label: string; path: string };
export type NavSection = { key: string; label: string; module: string; items: NavItem[] };

export async function fetchNavigation(): Promise<NavSection[]> {
  const body = await api<{ sections: NavSection[] }>("/api/me/navigation/", { cache: "no-store" });
  return body.sections;
}
