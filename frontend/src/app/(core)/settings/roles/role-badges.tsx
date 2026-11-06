import { StatusPill } from "@/core/components/StatusPill";
import type { Role } from "@/core/lib/rbac";

/** System, elevated and MFA markers, through the one StatusPill. Shared by the list and the editor. */
export function RoleBadges({ role }: { role: Role }) {
  return (
    <span className="inline-flex flex-wrap gap-1 align-middle">
      {role.is_system ? (
        <StatusPill
          status="rbac.role.system"
          title="Created by the system. It cannot be renamed, deleted, or have its grants changed."
        />
      ) : null}
      {role.is_elevated ? (
        <StatusPill status="rbac.role.elevated" title="Only a superuser can change or assign this role." />
      ) : null}
      {role.mfa_required ? (
        <StatusPill
          status="rbac.role.mfa_required"
          title="Everyone holding this role must use two-factor authentication."
        />
      ) : null}
    </span>
  );
}
