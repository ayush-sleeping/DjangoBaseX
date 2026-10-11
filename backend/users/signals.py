"""
users signals. `password_changed` is sent by User.save() for a real password change — never for a
login-time hash upgrade — and its receiver runs the § 6.7 cascade (users.services.passwords).
"""

from django.dispatch import Signal

password_changed = Signal()  # kwargs: user

# Sent when an invitation creates an account. rbac listens and assigns the invited role, so users
# never imports rbac (Ch. 2) and rbac never imports users' models. kwargs: user, role_id, invited_by
invitation_accepted = Signal()


def connect() -> None:
    from .services.passwords import on_password_changed

    password_changed.connect(on_password_changed, dispatch_uid="users.password_changed.cascade")
