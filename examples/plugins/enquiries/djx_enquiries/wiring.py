"""
Everything this plugin contributes to the platform, registered at boot from AppConfig.ready().
Imports core.sdk and nothing else (EXTENSIBILITY § 16); core never names this plugin.
"""

from core.sdk import (
    NavItem,
    NavSection,
    NumberingSeries,
    PermissionGroupSpec,
    PermissionSpec,
    Recyclable,
    ScopeSpec,
    StateField,
    StateMachine,
    register_recyclable,
    register_scoping,
    registry,
    require_version,
)

require_version("1.2")  # numbering, state machine and money arrived in SDK 1.2

VIEW = PermissionSpec(code="enquiries.enquiries.view", label="View enquiries")
CREATE = PermissionSpec(code="enquiries.enquiries.create", label="Create enquiries")
UPDATE = PermissionSpec(code="enquiries.enquiries.update", label="Edit enquiries")
TRANSITION = PermissionSpec(code="enquiries.enquiries.transition", label="Move enquiries on")
DELETE = PermissionSpec(code="enquiries.enquiries.delete", label="Delete enquiries")

GROUP = PermissionGroupSpec(
    code="enquiries",
    label="Enquiries",
    module="enquiries",
    permissions=(VIEW, CREATE, UPDATE, TRANSITION, DELETE),
)

SECTION = NavSection(
    key="enquiries",
    label="Enquiries",
    module="enquiries",
    items=(NavItem(key="home", label="Enquiries", href="/enquiries", permission=VIEW.code),),
)

# Gapless: reserved inside the create's transaction, so a rollback returns the number. A
# gap-tolerant series reserves on its own connection, which the default (transaction-wrapped)
# test database cannot host on in-memory SQLite: see TRAPS.md and SECOND_PRODUCT.md F2.
SERIES = NumberingSeries(
    key="enquiries.enquiry",
    label="Enquiries",
    pattern="{PREFIX}-{YYYY}-{seq:05}",
    reset="yearly",
    gapless=True,
    prefix="ENQ",
)

STATUS_KEY = "enquiries.enquiry.status"
# new → contacted → quoted → won; any open state → lost; lost → new reopens. Won is final.
MACHINE = StateMachine(
    key=STATUS_KEY,
    model="enquiries.Enquiry",
    field="status",
    initial="new",
    transitions={
        "new": {"contacted", "lost"},
        "contacted": {"quoted", "lost"},
        "quoted": {"won", "lost"},
        "lost": {"new"},
        "won": set(),
    },
    reason_required=frozenset(
        {("new", "lost"), ("contacted", "lost"), ("quoted", "lost"), ("lost", "new")}
    ),
)

AUDIT_ACTIONS = (
    ("enquiries.enquiry.created", "Enquiry created", "success"),
    ("enquiries.enquiry.updated", "Enquiry edited", "info"),
    ("enquiries.enquiry.deleted", "Enquiry deleted", "warning"),
)


def register() -> None:
    registry.permissions.register(GROUP)
    registry.api_routes.register(prefix="enquiries", urlconf="djx_enquiries.urls")
    registry.navigation.register(SECTION)
    registry.numbering.register(SERIES)
    registry.state_fields.register(
        StateField(key=STATUS_KEY, model="enquiries.Enquiry", field="status")
    )
    registry.state_machines.register(MACHINE)
    register_scoping(ScopeSpec("enquiries.Enquiry", owner_field="owner"))
    register_recyclable(
        Recyclable(
            key="enquiries.enquiry",
            model="enquiries.Enquiry",
            label="Enquiries",
            title_field="subject",
            delete_permission=DELETE.code,
        )
    )
    for key, label, tone in AUDIT_ACTIONS:
        registry.audit_actions.register(key=key, label=label, tone=tone, channel="enquiries")
