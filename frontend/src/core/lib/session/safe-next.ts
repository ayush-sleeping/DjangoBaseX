/**
 * Where to go after signing in (FRONTEND_PLATFORM § 8.2). `next` arrives in the URL, so it is
 * attacker-controlled: only a same-origin relative path is accepted, or sign-in becomes an open
 * redirect — a phishing kit hosted on our own domain. Anything else falls back to "/".
 */
export const DEFAULT_NEXT = "/";

export function safeNext(value: string | null | undefined): string {
  if (!value || typeof value !== "string") return DEFAULT_NEXT;
  // One leading slash, then not a second slash or a backslash: "//evil" and "/\evil" are
  // protocol-relative to browsers. No scheme, no control characters (a tab or newline inside
  // "/\t/evil" is stripped by URL parsers, leaving "//evil").
  if (!value.startsWith("/") || value.startsWith("//") || value.startsWith("/\\")) return DEFAULT_NEXT;
  if (/[\\\u0000-\u001f\u007f]/.test(value)) return DEFAULT_NEXT;
  // Resolve against a throwaway origin: whatever survives must still be on that origin.
  try {
    const probe = new URL(value, "http://same-origin.invalid");
    if (probe.origin !== "http://same-origin.invalid") return DEFAULT_NEXT;
    return `${probe.pathname}${probe.search}${probe.hash}`;
  } catch {
    return DEFAULT_NEXT;
  }
}
