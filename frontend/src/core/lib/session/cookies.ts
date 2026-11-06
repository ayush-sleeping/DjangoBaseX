/**
 * The auth cookies' names as the frontend sees them (backend/users/cookies.py decides them). The
 * prefix is the deployment's (NEXT_PUBLIC_AUTH_COOKIE_PREFIX, else the shipped default), and each
 * cookie may carry `__Host-` (Secure, no shared domain) or not, so both spellings are accepted.
 *
 * The frontend reads two cookies by name and no others: the CSRF token (echoed on unsafe methods)
 * and the session MARKER (src/proxy.ts). It never reads the access or refresh cookie: they are
 * httpOnly, and the page-navigation guard must not depend on them (FRONTEND_PLATFORM § 8.2).
 */
import { SHIPPED_COOKIE_PREFIX } from "@/core/lib/identity-defaults";

export const AUTH_COOKIE_PREFIX = process.env.NEXT_PUBLIC_AUTH_COOKIE_PREFIX || SHIPPED_COOKIE_PREFIX;

/** Both spellings of `<prefix>_<suffix>`: plain and `__Host-` prefixed. */
export function authCookieNames(suffix: "csrf" | "session"): ReadonlySet<string> {
  const name = `${AUTH_COOKIE_PREFIX}_${suffix}`;
  return new Set([name, `__Host-${name}`]);
}
