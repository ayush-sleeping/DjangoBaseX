"""Project the code catalog onto the database (AUTH_BLUEPRINT § 7.3). Idempotent. NEVER deletes."""

from dataclasses import dataclass, field

from django.db import transaction

from core.registry import registry

from .models import Permission, PermissionGroup
from .selectors import bump_version


@dataclass
class SyncReport:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    deprecated: list[str] = field(default_factory=list)
    restored: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.created or self.updated or self.deprecated or self.restored)


@transaction.atomic
def sync_catalog() -> SyncReport:
    report = SyncReport()
    catalog_codes = set()
    for spec_group in registry.permissions.groups():
        group, _ = PermissionGroup.objects.update_or_create(
            code=spec_group.code,
            defaults={
                "label": spec_group.label,
                "module": spec_group.module,
                "order": spec_group.order,
            },
        )
        for spec in spec_group.permissions:
            catalog_codes.add(spec.code)
            existing = Permission.objects.filter(code=spec.code).first()
            if existing is None:
                Permission.objects.create(
                    code=spec.code, label=spec.label, group=group, module=spec_group.module
                )
                report.created.append(spec.code)
                continue
            changed = (existing.label, existing.group_id, existing.module) != (
                spec.label,
                group.pk,
                spec_group.module,
            )
            if existing.is_deprecated:
                report.restored.append(spec.code)
            elif changed:
                report.updated.append(spec.code)
            if changed or existing.is_deprecated:
                existing.label, existing.group, existing.module = (
                    spec.label,
                    group,
                    spec_group.module,
                )
                existing.is_deprecated = False
                existing.save(update_fields=["label", "group", "module", "is_deprecated"])

    # Gone from the code: deprecated, never deleted — deleting would cascade away real grants.
    for code in Permission.objects.filter(is_deprecated=False).exclude(code__in=catalog_codes):
        report.deprecated.append(code.code)
    Permission.objects.filter(code__in=report.deprecated).update(is_deprecated=True)

    if report.changed:
        bump_version()
    return report
