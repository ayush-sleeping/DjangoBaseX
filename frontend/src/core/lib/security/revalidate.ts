/**
 * The pure half of POST /fe/revalidate/ (FRONTEND_PLATFORM § 17): the shared-secret check and the
 * body's tag list. The route handler is the only caller; keeping this apart makes it testable
 * without Next.
 */
import { timingSafeEqual } from "node:crypto";

const TAG = /^identity(:[a-z0-9.-]{1,253})?$/;
const MAX_TAGS = 10;

/**
 * Constant-time compare. An unset or empty secret refuses everything (fail closed); a different
 * length refuses without comparing (timingSafeEqual throws on unequal lengths, and a length is not
 * a secret worth hiding when the secret is a fixed-length random token).
 */
export function secretMatches(configured: string | undefined, presented: string | null): boolean {
  if (!configured || !presented) return false;
  const a = Buffer.from(configured);
  const b = Buffer.from(presented);
  if (a.length !== b.length) return false;
  return timingSafeEqual(a, b);
}

/** `{ "tags": ["identity"] }` -> the tags; anything else -> null. Only identity tags are allowed. */
export function parseTags(body: unknown): string[] | null {
  if (typeof body !== "object" || body === null) return null;
  const tags = (body as { tags?: unknown }).tags;
  if (!Array.isArray(tags) || tags.length === 0 || tags.length > MAX_TAGS) return null;
  if (!tags.every((t): t is string => typeof t === "string" && TAG.test(t))) return null;
  return [...new Set(tags)];
}
