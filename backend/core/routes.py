"""
The public-route ledger (AUTH_BLUEPRINT.md § 9.2), as a registry seam (TECH_DEBT DB-22).

Every /api/ route must refuse an anonymous caller with 401 or 403. The exceptions are registered,
each with a sentence a reviewer can disagree with, into core.registry's public_routes: core's own
here, every other app's (and every plugin's) from its own AppConfig.ready(), so no app edits core
to open an endpoint. dbx.E007 and the route test read the union; test_public_routes pins it.
"""

from collections.abc import Mapping

CORE_PUBLIC_ROUTES: dict[str, str] = {
    "core:health": "Liveness probe for load balancers and the frontend. Reports status only.",
    "core:public-config": (
        "The product's display name and tagline, which the sign-in page shows before anyone signs "
        "in. Public by nature; no user data, no boot identity (CONFIGURATION.md § 7)."
    ),
    "schema": (
        "OpenAPI document: describes the API surface, holds no data. "
        "To be served only when DEBUG or SCHEMA_PUBLIC (AUTH_BLUEPRINT.md § 9.2)."
    ),
    "swagger-ui": "Docs UI over the schema. Same condition as the schema.",
}


def public_routes() -> Mapping[str, str]:
    """Every registered public route (url name -> reason), across core, apps and plugins."""
    from .registry import registry

    return registry.public_routes.routes()
