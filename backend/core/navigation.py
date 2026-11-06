"""
The navigation a signed-in user may follow, which is also the frontend's route gate
(FRONTEND_PLATFORM.md § 10, BUILD_ORDER 8.2).

Built on the server from registry.navigation and filtered by the user's EFFECTIVE permissions, so
the menu and the API never disagree about who may do what. The frontend draws the items that are
not `hidden` and gates every page on the deepest-prefix match over ALL of them: a page with no
entry is denied. It only shapes a menu and a page: every endpoint behind an item still decides for
itself. core reads permissions through Django's user.get_all_permissions(), never through rbac.

full_manifest() is the unfiltered catalogue the frontend's build-time checks read, committed as
frontend/src/generated/nav-manifest.json by `manage.py export_frontend_contracts`
(core/contracts.py) and kept in step by tests/test_contracts_export.py.
"""

from .registry import NavItem, registry


def _item(item: NavItem) -> dict:
    return {
        "key": item.key,
        "label": item.label,
        "href": item.href,
        "permission": item.permission,
        "hidden": item.hidden,
        "public": item.public,
        "exact": item.exact,
    }


def _sections(sections) -> list[dict]:
    return [
        {
            "key": section.key,
            "label": section.label,
            "module": section.module,
            "items": [_item(item) for item in section.items],
        }
        for section in sections
    ]


def navigation_for(user) -> list[dict]:
    """Sections and items visible to `user`, in registry order. Empty sections are dropped."""
    codes = frozenset(user.get_all_permissions())
    return _sections(registry.navigation.visible_to(codes, user.is_superuser))


def full_manifest(exclude_modules: frozenset[str] = frozenset()) -> dict:
    """Every registered section and item, unfiltered: the input to the frontend route checks.
    The committed file excludes linked plugins' modules: it is the boilerplate's own manifest,
    identical whether or not a plugin is installed."""
    sections = [s for s in registry.navigation.sections() if s.module not in exclude_modules]
    return {"sections": _sections(sections)}
