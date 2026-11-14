/**
 * POST /fe/revalidate/: the backend tells the frontend that the identity it cached is stale
 * (FRONTEND_PLATFORM § 17 "Save shows immediately"). Server to server, never a browser.
 *
 * Authenticated by a shared secret in `x-revalidate-secret`, read from REVALIDATE_SECRET at
 * request time. Unset: the route refuses everything. The secret is never logged.
 */
import { revalidateTag } from "next/cache";

import { parseTags, secretMatches } from "@/core/lib/security/revalidate";

export async function POST(request: Request): Promise<Response> {
  if (!secretMatches(process.env.REVALIDATE_SECRET, request.headers.get("x-revalidate-secret"))) {
    return new Response(null, { status: 401 });
  }
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return new Response(null, { status: 400 });
  }
  const tags = parseTags(body);
  if (!tags) return new Response(null, { status: 400 });
  // expire: 0, not stale-while-revalidate: the person who just saved is looking at the page.
  for (const tag of tags) revalidateTag(tag, { expire: 0 });
  return new Response(null, { status: 204 });
}
