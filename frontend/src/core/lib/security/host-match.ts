/**
 * Exact host classification (FRONTEND_PLATFORM § 17 "Host classification is exact").
 *
 * Lowercase, strip the port and a trailing dot, compare for equality. Never `includes()`, never an
 * `endsWith()` without a dot boundary: `not-app.example.test.attacker.example` is not a workspace.
 * The core knows one identity (the platform's); per-tenant hosts belong to the white-label module
 * (REUSABLE_MODULES.md, TECH_DEBT DB-91), which supplies its own known-host table.
 */

/** "App.Example.Test.:8443" -> "app.example.test"; null when it is not a plausible host name. */
export function normalizeHost(raw: string | null | undefined): string | null {
  if (!raw) return null;
  let host = raw.trim().toLowerCase();
  if (host.startsWith("[")) return null; // IPv6 literals are never a configured product host
  host = host.replace(/:\d{1,5}$/, "").replace(/\.$/, "");
  if (!/^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*$/.test(host)) return null;
  return host;
}

export type HostClass = "platform" | "unknown";

/** "platform" only on an exact match with the primary host or one of the allowed hosts. */
export function classifyHost(
  raw: string | null | undefined,
  known: { primary: string; allowed?: readonly string[] },
): HostClass {
  const host = normalizeHost(raw);
  if (!host) return "unknown";
  const table = [known.primary, ...(known.allowed ?? [])].map(normalizeHost);
  return table.includes(host) ? "platform" : "unknown";
}
