"""The user model — identity only. Nothing about permissions lives here (AUTH_BLUEPRINT § 3.1)."""

import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.db.models.functions import Lower


def normalize_email(email: str) -> str:
    """The one email normalisation: trimmed and lowercased, local part included."""
    return email.strip().lower()


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("An email address is required.")
        user = self.model(email=normalize_email(email), **extra_fields)
        user.set_password(password)  # None → an unusable password
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        # The one creation path that activates explicitly — see `is_active` below.
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields["is_staff"] is not True or extra_fields["is_superuser"] is not True:
            raise ValueError("A superuser must have is_staff=True and is_superuser=True.")
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """Signs in with an email address; there is no username (ADR-0008)."""

    # Internal ids never appear in a URL (A15); the API exposes `public_id`.
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    email = models.EmailField(max_length=254, unique=True)
    full_name = models.CharField(max_length=255, blank=True, default="")

    # Defaults to False on purpose: a row created by any path (admin, shell, fixture) cannot sign
    # in until something explicitly activates it. create_superuser() is the one path that does.
    is_active = models.BooleanField(default=False, db_index=True)
    # Django admin access only, and full trust when granted. Not an authorization concept.
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False, db_index=True)
    mfa_enforced = models.BooleanField(default=False)

    password_changed_at = models.DateTimeField(null=True, blank=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)
    deactivated_reason = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        db_table = "users_user"
        ordering = ["email"]
        constraints = [
            # The database refuses a mixed-case address, so "two accounts, one email" cannot
            # happen through the admin, a shell or a data migration either.
            models.CheckConstraint(
                condition=models.Q(email=Lower("email")),
                name="users_user_email_lowercase",
            ),
        ]

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        self.email = normalize_email(self.email)
        super().save(*args, **kwargs)
