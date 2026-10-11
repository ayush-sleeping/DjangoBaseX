"""
Factories for every model. Defaults describe the common case: an active user with no special
trust. A test that needs something unusual says so in its arguments.
"""

import factory

from users.models import User

DEFAULT_PASSWORD = "correct-horse-battery-staple"


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    full_name = factory.Sequence(lambda n: f"Test User {n}")
    is_active = True
    password = factory.django.Password(DEFAULT_PASSWORD)
