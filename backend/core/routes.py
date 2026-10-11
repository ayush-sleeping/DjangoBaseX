"""
PUBLIC_ROUTES — the exemption ledger (AUTH_BLUEPRINT.md § 9.2).

Every /api/ route must refuse an anonymous caller with 401 or 403. These are the only exceptions.
Keys are URL *names*, so a renamed route loses its exemption loudly instead of quietly. Every value
is a sentence a reviewer can disagree with. The list only grows by argument: adding to it opens
something to the internet, and tests/architecture/test_public_routes.py pins its contents so that
needs a deliberate, reviewed edit.
"""

PUBLIC_ROUTES: dict[str, str] = {
    "core:health": "Liveness probe for load balancers and the frontend. Reports status only.",
    "schema": (
        "OpenAPI document: describes the API surface, holds no data. "
        "To be served only when DEBUG or SCHEMA_PUBLIC (AUTH_BLUEPRINT.md § 9.2)."
    ),
    "swagger-ui": "Docs UI over the schema. Same condition as the schema.",
    "users:login": "The front door. Same answer for every failure; attempts recorded (Ch. 6.2).",
    "users:password-forgot": "Pre-authentication by definition. Always answers 204 (Ch. 6.6).",
    "users:password-reset": "Authenticated by the single-use reset token itself (Ch. 6.6).",
    "users:mfa-verify": "Authenticated by the password step's single-use mfa_token (Ch. 6.8).",
    "users:refresh": "Authenticated by the refresh cookie itself, not an access token (Ch. 6.3).",
}
