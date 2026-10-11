"""
The user in the Django admin — read-mostly (AUTH_BLUEPRINT.md Ch. 20).

No raw password field, and `is_staff` / `is_superuser` are not editable here: both are full trust,
and granting them belongs to an audited service, not a checkbox.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm

from .models import User


class UserCreationAdminForm(AdminUserCreationForm):
    class Meta:
        model = User
        fields = ("email", "full_name")


class UserChangeAdminForm(UserChangeForm):
    class Meta:
        model = User
        fields = ("email", "full_name", "is_active")


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = UserChangeAdminForm
    add_form = UserCreationAdminForm

    list_display = ("email", "full_name", "is_active", "is_staff", "is_superuser", "created_at")
    list_filter = ("is_active", "is_staff", "is_superuser")
    search_fields = ("email", "full_name")
    ordering = ("email",)
    # Django's groups / user_permissions are not used — roles live in `rbac` (AUTH_BLUEPRINT A9).
    filter_horizontal = ()

    readonly_fields = (
        "public_id",
        "is_staff",
        "is_superuser",
        "mfa_enforced",
        "last_login",
        "password_changed_at",
        "deactivated_at",
        "deactivated_reason",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (None, {"fields": ("public_id", "email", "password")}),
        ("Profile", {"fields": ("full_name",)}),
        ("Status", {"fields": ("is_active", "deactivated_at", "deactivated_reason")}),
        ("Trust — not editable here", {"fields": ("is_staff", "is_superuser", "mfa_enforced")}),
        ("Dates", {"fields": ("last_login", "password_changed_at", "created_at", "updated_at")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "full_name", "usable_password", "password1", "password2"),
            },
        ),
    )
