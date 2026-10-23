/**
 * The shipped identity defaults, mirroring backend/core/identity.py (CONFIGURATION.md § 7). The
 * ONE frontend module that spells them; no imports, so api.ts can read the cookie prefix from it.
 *
 * They announce themselves: a page that shows "Unnamed product" is a deployment nobody named yet.
 */
export const SHIPPED_PRODUCT_NAME = "Unnamed product";
export const SHIPPED_TAGLINE = "Rename this deployment — set PRODUCT_NAME";
/** cookie_prefix(product_slug(SHIPPED_PRODUCT_NAME)) on the backend. */
export const SHIPPED_COOKIE_PREFIX = "unnamed_product";
