"""users.User and its manager — the ADR-0008 guarantees, each one a test."""

import pytest
from django.contrib.auth import authenticate, get_user_model
from django.db import IntegrityError, transaction

from tests.factories import DEFAULT_PASSWORD, UserFactory

User = get_user_model()

pytestmark = pytest.mark.django_db


def test_auth_user_model_is_email_identified_with_no_username():
    assert User._meta.label == "users.User"
    assert User.USERNAME_FIELD == "email"
    assert not hasattr(User, "username")


def test_create_user_normalises_email_and_starts_inactive():
    user = User.objects.create_user("  Alice@Example.COM ", "x-long-enough-password")

    assert user.email == "alice@example.com"
    assert user.is_active is False
    assert user.public_id is not None


def test_create_user_without_password_gets_an_unusable_one():
    assert not User.objects.create_user("sso@example.com").has_usable_password()


def test_create_user_requires_an_email():
    with pytest.raises(ValueError):
        User.objects.create_user("", "x-long-enough-password")


def test_inactive_user_cannot_authenticate_until_activated():
    user = UserFactory(is_active=False)
    assert authenticate(email=user.email, password=DEFAULT_PASSWORD) is None

    user.is_active = True
    user.save()
    assert authenticate(email=user.email, password=DEFAULT_PASSWORD) == user


def test_create_superuser_is_the_one_path_that_activates():
    user = User.objects.create_superuser("root@example.com", "x-long-enough-password")
    assert (user.is_active, user.is_staff, user.is_superuser) == (True, True, True)


def test_create_superuser_refuses_to_drop_its_flags():
    with pytest.raises(ValueError):
        User.objects.create_superuser("root@example.com", "pw", is_staff=False)


def test_emails_differing_only_in_case_are_one_account():
    UserFactory(email="alice@example.com")
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create_user("ALICE@example.com", "pw")


def test_database_refuses_a_mixed_case_email_written_around_the_model():
    user = UserFactory()
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.filter(pk=user.pk).update(email="Mixed@Example.com")
