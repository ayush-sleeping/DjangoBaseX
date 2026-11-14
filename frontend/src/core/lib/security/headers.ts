/**
 * The static security headers (FRONTEND_PLATFORM § 18 "Rules — static headers", BUILD_ORDER 8.5b).
 *
 * Pure and tested here; `next.config.ts`'s `headers()` only wires it in. The per-request CSP is not
 * in this list: it needs a nonce, so `src/proxy.ts` owns it.
 */
type SecurityHeader = { key: string; value: string };

/** Two years, subdomains included. `preload` is deliberately absent: that is a one-way submission. */
export const HSTS_VALUE = "max-age=63072000; includeSubDomains";

/** HSTS only in production: on http://localhost it would pin the browser to https for two years. */
export function securityHeaders({ isProduction }: { isProduction: boolean }): SecurityHeader[] {
  const headers: SecurityHeader[] = [
    { key: "X-Content-Type-Options", value: "nosniff" },
    // CSP frame-ancestors 'none' is the modern control; this covers browsers that ignore it.
    { key: "X-Frame-Options", value: "DENY" },
    { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
    { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
    { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
    // "0" disables the legacy XSS auditor, which introduced holes of its own.
    { key: "X-XSS-Protection", value: "0" },
  ];
  if (isProduction) headers.push({ key: "Strict-Transport-Security", value: HSTS_VALUE });
  return headers;
}
