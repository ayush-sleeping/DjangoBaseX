"use client";

// Client component: roles are authenticated data, and the session is an httpOnly cookie.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";

import { DataTable, type DataTableColumn, Pager } from "@/core/components/data-table";
import { EmptyState } from "@/core/components/EmptyState";
import { ListLoadError } from "@/core/components/ListLoadError";
import { fieldErrors, isMfaEnrollmentRequired } from "@/core/lib/api";
import { MFA_ENROLMENT_PATH } from "@/core/lib/mfa";
import { usePermissions } from "@/core/lib/permissions";
import { useApiList } from "@/core/lib/query";
import {
  createRole,
  listRoles,
  type Role,
  ROLE_CODES,
  rbacErrorMessage,
  roleKeys,
  suggestSlug,
} from "@/core/lib/rbac";

import { RoleBadges } from "./role-badges";

// ui-contract-deviation: the roles screens are not yet a module on the shells (follow-up after
// BUILD_ORDER 8.3b); their list already renders through the DataTable.
const ROLE_COLUMNS: DataTableColumn<Role>[] = [
  {
    id: "role",
    kind: "identifier",
    header: "Role",
    cell: (role) => (
      <div className="min-w-0">
        <Link className="font-medium underline-offset-4 hover:underline" href={`/settings/roles/${encodeURIComponent(role.public_id)}`}>
          {role.name}
        </Link>{" "}
        <RoleBadges role={role} />
        <span className="block font-mono text-xs text-muted-foreground">{role.slug}</span>
      </div>
    ),
  },
  { id: "permissions", kind: "data", header: "Permissions", align: "end", cell: (role) => role.permissions.length },
  { id: "users", kind: "data", header: "Users", align: "end", cell: (role) => role.user_count },
];

const card = "w-full max-w-3xl space-y-4 rounded-xl border border-border p-6";
const input =
  "mt-1 w-full rounded-md border border-input px-3 py-2";
const button =
  "rounded-md bg-primary px-3 py-2 text-sm text-primary-foreground disabled:opacity-50";

export function RolesPanel() {
  const router = useRouter();
  const perms = usePermissions();
  const allowed = perms.can(ROLE_CODES.view);
  const [page, setPage] = useState(1);
  // The role editor still writes through plain functions (not useApiMutation), so nothing
  // invalidates this list after an edit: refetch on every visit until the roles screens become a
  // module (follow-up after BUILD_ORDER 8.3b).
  const roles = useApiList<Role>(roleKeys.list(page), (signal) => listRoles(page, signal), {
    enabled: allowed,
    refetchOnMount: "always",
  });

  useEffect(() => {
    if (isMfaEnrollmentRequired(roles.error)) router.push(MFA_ENROLMENT_PATH);
  }, [roles.error, router]);

  if (perms.status === "loading") return <p className="text-sm text-muted-foreground">Checking your session…</p>;
  if (perms.permissionsError && !perms.signedOut) {
    return (
      <p role="alert" className="text-sm text-destructive">
        Could not reach the server. Reload the page to try again.
      </p>
    );
  }
  if (!perms.user) {
    return (
      <section className={card}>
        <p className="text-sm">Sign in to manage roles.</p>
        <Link className="block text-sm underline" href="/login">
          Sign in
        </Link>
      </section>
    );
  }
  if (!allowed) {
    return <p className="text-sm">You don&apos;t have permission to view roles.</p>;
  }


  return (
    <div className="flex w-full flex-col items-center gap-6">
      <section className={card}>
        {roles.showError ? (
          <ListLoadError {...roles.listErrorProps} resource="roles" />
        ) : (
          <>
            <DataTable<Role>
              caption="Roles"
              columns={ROLE_COLUMNS}
              rows={roles.items}
              getRowId={(role) => role.public_id}
              getRowLabel={(role) => role.name}
              loading={roles.isLoading}
              fetching={roles.isFetching}
              empty={roles.isEmpty ? <EmptyState variant="none" title="No roles yet" /> : null}
            />
            {roles.count > 0 ? (
              <Pager page={page} count={roles.count} onPage={setPage} noun="roles" disabled={roles.isFetching} />
            ) : null}
          </>
        )}
      </section>

      {perms.can(ROLE_CODES.create) ? (
        <CreateRoleForm
          showElevated={perms.user?.is_superuser === true}
          onCreated={(role) =>
            router.push(`/settings/roles/${encodeURIComponent(role.public_id)}`)
          }
        />
      ) : null}
    </div>
  );
}

function CreateRoleForm({
  showElevated,
  onCreated,
}: {
  showElevated: boolean;
  onCreated: (role: Role) => void;
}) {
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugEdited, setSlugEdited] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string>();
  const [fields, setFields] = useState<Record<string, string[]>>({});

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setPending(true);
    try {
      const role = await createRole({
        name,
        slug,
        description: String(form.get("description") ?? ""),
        mfa_required: form.get("mfa_required") === "on",
        // Only a superuser may set it (403 elevated_requires_superuser); others never send it.
        ...(showElevated ? { is_elevated: form.get("is_elevated") === "on" } : {}),
      });
      onCreated(role);
    } catch (err) {
      setError(rbacErrorMessage(err));
      setFields(fieldErrors(err));
      setPending(false);
    }
  }

  const fieldError = (field: string) =>
    fields[field]?.length ? (
      <span className="mt-1 block text-xs text-destructive">{fields[field].join(" ")}</span>
    ) : null;

  return (
    <form onSubmit={handleSubmit} className={card} noValidate>
      <h2 className="text-sm font-semibold">New role</h2>
      <p className="text-xs text-muted-foreground">
        A new role holds no permissions. Grant them on the next screen.
      </p>
      <label className="block text-sm">
        Name
        <input
          name="name"
          required
          value={name}
          onChange={(event) => {
            setName(event.target.value);
            if (!slugEdited) setSlug(suggestSlug(event.target.value));
          }}
          className={input}
        />
        {fieldError("name")}
      </label>
      <label className="block text-sm">
        Slug <span className="text-xs text-muted-foreground">(permanent: it cannot be changed later)</span>
        <input
          name="slug"
          required
          value={slug}
          onChange={(event) => {
            setSlug(event.target.value);
            setSlugEdited(true);
          }}
          className={`${input} font-mono`}
        />
        {fieldError("slug")}
      </label>
      <label className="block text-sm">
        Description
        <textarea name="description" rows={2} className={input} />
        {fieldError("description")}
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" name="mfa_required" />
        Require two-factor authentication for everyone holding this role
      </label>
      {showElevated ? (
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" name="is_elevated" />
          Elevated: only a superuser can change or assign it
        </label>
      ) : null}
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
      <button type="submit" disabled={pending} className={button}>
        {pending ? "Creating…" : "Create role"}
      </button>
    </form>
  );
}
