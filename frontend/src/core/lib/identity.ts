/**
 * The product's display identity, from GET /api/public/config/ (CONFIGURATION.md § 7).
 *
 * The frontend never reads the product name from env: a rename is a backend restart, not a
 * frontend rebuild. Cached for a minute, so the root layout does not ask Django on every request.
 */
import { SHIPPED_LOCALIZATION } from "@/generated/localization";

import { api } from "./api";
import { SHIPPED_PRODUCT_NAME, SHIPPED_TAGLINE } from "./identity-defaults";

/** Also the platform's locale and timezone: what signed-out pages and server rendering use. */
export type Identity = { product_name: string; tagline: string; locale: string; timezone: string };

const REVALIDATE_SECONDS = 60;

/** Never throws: with the API unreachable, a page still renders, under the shipped defaults. */
export async function getIdentity(): Promise<Identity> {
  try {
    return await api<Identity>("/api/public/config/", {
      next: { revalidate: REVALIDATE_SECONDS },
    });
  } catch {
    return {
      product_name: SHIPPED_PRODUCT_NAME,
      tagline: SHIPPED_TAGLINE,
      locale: SHIPPED_LOCALIZATION.locale,
      timezone: SHIPPED_LOCALIZATION.timezone,
    };
  }
}
