"""
Where this product plugs into the platform (EXTENSIBILITY.md § 6): permissions, navigation, API
routes and health checks are registered here, at boot, and never by editing platform code.

    from core.registry import NavItem, NavSection, PermissionGroupSpec, PermissionSpec, registry

    registry.permissions.register(PermissionGroupSpec(
        code="enquiries", label="Enquiries", module="enquiries",
        permissions=(PermissionSpec("enquiries.enquiries.view", "View enquiries"),),
    ))
    registry.api_routes.register(prefix="enquiries", urlconf="project.enquiries.urls")

The boilerplate ships this empty: a product's first module starts here.
"""


def register() -> None:
    """Called from ProjectConfig.ready(). Registers nothing until the product adds something."""
