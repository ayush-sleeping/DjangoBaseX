"""
Core's declarations for registry.scoping (DATA_LIFECYCLE.md § 12.1). Every model with an owner or
tenant field is here, scoped or explicitly not, with the reason. ADR-0011: core has no organisation
model, so "scoped" means a visible_to() on the queryset, and nothing here names a tenant table.

Own-row models (Notification, NotificationPreference) are filtered by their API to
`request.user`; converting them to a VisibleToQuerySet is TECH_DEBT DB-123.
"""

from .registry import ScopeSpec

ADMIN_MANAGED = (
    "Managed only by staff holding its permission codes through an admin API; created_by is an "
    "audit stamp, not visibility."
)

SPECS = (
    ScopeSpec("core.ApiConsumer", owner_field="created_by", not_scoped_because=ADMIN_MANAGED),
    ScopeSpec("core.ApiToken", owner_field="created_by", not_scoped_because=ADMIN_MANAGED),
    ScopeSpec("core.WebhookEndpoint", owner_field="created_by", not_scoped_because=ADMIN_MANAGED),
    ScopeSpec("core.NotificationRoute", owner_field="created_by", not_scoped_because=ADMIN_MANAGED),
    ScopeSpec(
        "core.FeatureFlag",
        tenant_field="tenant_ids",
        not_scoped_because=(
            "Platform-wide flag table read by flag evaluation; tenant_ids is a targeting list "
            "(ADR-0011: no tenant model in core), not a per-tenant row owner."
        ),
    ),
    ScopeSpec(
        "core.Notification",
        owner_field="recipient",
        not_scoped_because=(
            "Own rows only: the one API that lists it filters recipient=request.user "
            "(core/api/notifications.py _own)."
        ),
    ),
    ScopeSpec(
        "core.NotificationPreference",
        owner_field="user",
        not_scoped_because=(
            "Own rows only: its endpoint reads and writes the signed-in user's preferences."
        ),
    ),
    ScopeSpec(
        "core.NotificationDelivery",
        owner_field="recipient",
        not_scoped_because=(
            "Internal delivery ledger written by the dispatcher; no viewset lists it per "
            "recipient (the user-facing list is Notification)."
        ),
    ),
    ScopeSpec(
        "core.PrivateFile",
        owner_field="uploaded_by",
        not_scoped_because=(
            "Authorised by the upload purpose's read permission, answering 404 otherwise "
            "(core/api/files.py), not by uploader."
        ),
    ),
)


def register(registry) -> None:
    for spec in SPECS:
        registry.scoping.register(spec)
