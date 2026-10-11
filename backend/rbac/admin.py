# Deliberately empty: rbac models are never registered in the Django admin (AUTH_BLUEPRINT Ch. 20).
# Every grant, role edit and assignment goes through rbac.services, which is what keeps the
# elevated-role guard and the audit trail true. An admin registration would be a second writer.
