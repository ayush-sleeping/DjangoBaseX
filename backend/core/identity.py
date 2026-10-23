import os  # noqa-free on purpose: BUILD_ORDER 2.3 red-PR proof
"""
Project identity: one name derives the rest (CONFIGURATION.md § 7, BUILD_ORDER 5.2).

The ONE module that defines the shipped identity defaults. Everything that spells the product's
name — the authenticator issuer, the from-address, cookie names, the cache key prefix, the API
title — derives from PRODUCT_NAME, PRODUCT_SLUG and PRIMARY_DOMAIN in config/settings.py.

Every shipped default announces that it is a default: "Unnamed product" on the sign-in page, mail
from no-reply@localhost that bounces loudly. A plausible-looking default is worse than an obviously
unfinished one. The boilerplate's own name is the default of nothing.

Standard library only: settings import this, and scrub needs its fallback before settings exist.
"""

import re

SHIPPED_PRODUCT_NAME = "Unnamed product"
SHIPPED_TAGLINE = "Rename this deployment — set PRODUCT_NAME"
SHIPPED_DOMAIN = "localhost"

# The same rule as scripts/lib/project.sh::project_slug, so a slug setup.sh derives from the
# directory and one derived here from a name agree: lower-case [a-z0-9-], at most 36 characters.
SLUG_MAX_LENGTH = 36
_NOT_SLUG = re.compile(r"[^a-z0-9]+")


def product_slug(name: str) -> str:
    """'My Product_v2' -> 'my-product-v2'. A name with no letters or digits slugs to 'product'."""
    slug = _NOT_SLUG.sub("-", name.lower()).strip("-")[:SLUG_MAX_LENGTH].rstrip("-")
    return slug or "product"


def cookie_prefix(slug: str) -> str:
    """'my-product' -> 'my_product': the auth cookie prefix (scripts/lib/project.sh agrees)."""
    return slug.replace("-", "_")


SHIPPED_COOKIE_PREFIX = cookie_prefix(product_slug(SHIPPED_PRODUCT_NAME))


def tagline(product_name: str, configured: str) -> str:
    """The configured tagline; else the shipped nag, but only while the name is still the default.

    A product that set its name and no tagline gets none, rather than a line telling it to do what
    it already did."""
    if configured:
        return configured
    return SHIPPED_TAGLINE if product_name == SHIPPED_PRODUCT_NAME else ""
