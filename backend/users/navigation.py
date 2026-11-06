"""
The users app's pages in the navigation, which is also the route gate (FRONTEND_PLATFORM § 10):
every page under frontend/src/app needs an entry here or in another app's navigation, or the
frontend refuses it (default-deny). Registered from UsersConfig.ready().

The shell's own pages (home, sign-in and the other signed-out pages, the account screen) live
here too: they are identity pages, and core never registers navigation itself.
"""

from core.registry import NavItem, NavSection, registry

HOME = NavSection(
    key="home",
    label="Home",
    module="users",
    order=0,
    # The status page: public, so the sign-in page's "Back to the status page" link never loops.
    items=(NavItem("home", "Home", "/", exact=True, public=True),),
)

# Signed-out pages: reachable without a session, never drawn in the menu.
AUTH = NavSection(
    key="auth",
    label="Sign in",
    module="users",
    order=1000,
    items=(
        NavItem("login", "Sign in", "/login", hidden=True, public=True),
        NavItem("forgot-password", "Forgot password", "/forgot-password", hidden=True, public=True),
        NavItem("reset-password", "Reset password", "/reset-password", hidden=True, public=True),
        NavItem(
            "accept-invitation", "Accept invitation", "/accept-invitation", hidden=True, public=True
        ),
    ),
)

ACCOUNT = NavSection(
    key="account",
    label="Account",
    module="users",
    order=900,
    items=(NavItem("security", "Security", "/account/security"),),
)

# /users/<publicId> is gated by the "/users" prefix: the detail page needs the same code as the
# list. Pages that need a different code get their own (hidden) entry.
PEOPLE = NavSection(
    key="people",
    label="People",
    module="users",
    order=10,
    items=(
        NavItem("users", "Users", "/users", permission="users.users.view"),
        NavItem(
            "invitations", "Invitations", "/users/invitations", permission="users.invitations.send"
        ),
        NavItem("new", "New user", "/users/new", permission="users.users.create", hidden=True),
    ),
)


def register() -> None:
    for section in (HOME, PEOPLE, ACCOUNT, AUTH):
        registry.navigation.register(section)
