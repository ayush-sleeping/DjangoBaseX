"""The users module's domain events (registered in UsersConfig.ready; JOBS § 16).
`external=True` puts an event in the webhook catalogue: each needs an emit() call site."""

from core.registry import EventDef

EVENTS = (
    EventDef(
        name="users.user.created",
        description="An account was created.",
        object_type="user",
        external=True,
    ),
    EventDef(
        name="users.user.deactivated",
        description="An account was deactivated and can no longer sign in.",
        object_type="user",
        external=True,
    ),
)
