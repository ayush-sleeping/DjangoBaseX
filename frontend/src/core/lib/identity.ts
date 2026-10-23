/**
 * The product's display identity, from GET /api/public/config/ (CONFIGURATION.md § 7).
 *
 * The frontend never reads the product name from env: a rename is a backend restart, not a
 * frontend rebuild. Cached for a minute, so the root layout does not ask Django on every request.
 */
import { api } from "./api";
import { SHIPPED_PRODUCT_NAME, SHIPPED_TAGLINE } from "./identity-defaults";

export type Identity = { product_name: string; tagline: string };

const REVALIDATE_SECONDS = 60;

/** Never throws: with the API unreachable, a page still renders, under the shipped defaults. */
export async function getIdentity(): Promise<Identity> {
  try {
    return await api<Identity>("/api/public/config/", {
      next: { revalidate: REVALIDATE_SECONDS },
    });
  } catch {
    return { product_name: SHIPPED_PRODUCT_NAME, tagline: SHIPPED_TAGLINE };
  }
}
