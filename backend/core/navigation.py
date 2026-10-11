"""
The navigation a signed-in user may follow (FRONTEND_PLATFORM.md § 8; the first slice of
BUILD_ORDER 8.2).

Built on the server from registry.navigation and filtered by the user's EFFECTIVE permissions, so
the menu and the API never disagree about who may do what. It only shapes a menu: every endpoint
behind an item still decides for itself. core reads permissions through Django's
user.get_all_permissions(), never through rbac (Ch. 2).
"""

from .registry import registry


def navigation_for(user) -> list[dict]:
    """Sections and items visible to `user`, in registry order. Empty sections are dropped."""
    codes = frozenset(user.get_all_permissions())
    return [
        {
            "key": section.key,
            "label": section.label,
            "module": section.module,
            "items": [
                {"key": item.key, "label": item.label, "path": item.path} for item in section.items
            ],
        }
        for section in registry.navigation.visible_to(codes, user.is_superuser)
    ]
