"""Layer 2 — object scoping (AUTH_BLUEPRINT § 7.6, A13, DATA_MODEL.md § 5)."""

from django.db import models


class VisibleToQuerySet(models.QuerySet):
    """
    Every listable model's queryset subclasses this and implements visible_to(user). It MUST fail
    closed: no rule for this user means .none(), never .all(). It is also the one seam a product
    adding tenancy changes, per model, instead of changing every view (DATA_MODEL.md D3).
    """

    def visible_to(self, user):
        raise NotImplementedError(
            f"{self.model.__name__} must implement visible_to(). "
            "Returning .all() is a decision; make it explicitly."
        )

    def writable_by(self, user):
        """
        What `user` may change (DATA_LIFECYCLE.md § 12.4). Defaults to what they may see, so an
        invisible row is a 404 on PATCH/PUT/DELETE, never a 403 that confirms it exists. A model
        whose write rule is narrower than its read rule overrides this and intersects.
        """
        return self.visible_to(user)
