import type { Role } from "@/lib/rbac";

const badge = "rounded px-1.5 py-0.5 text-xs";

/** System, elevated and MFA markers. Shared by the list and the editor; renders on either side. */
export function RoleBadges({ role }: { role: Role }) {
  return (
    <span className="inline-flex flex-wrap gap-1 align-middle">
      {role.is_system ? (
        <span
          className={`${badge} bg-zinc-200 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300`}
          title="Created by the system. It cannot be renamed, deleted, or have its grants changed."
        >
          🔒 System
        </span>
      ) : null}
      {role.is_elevated ? (
        <span
          className={`${badge} bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300`}
          title="Only a superuser can change or assign this role."
        >
          Elevated
        </span>
      ) : null}
      {role.mfa_required ? (
        <span
          className={`${badge} bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300`}
          title="Everyone holding this role must use two-factor authentication."
        >
          Two-factor required
        </span>
      ) : null}
    </span>
  );
}
