"use client";

// Client component: roles are authenticated data, and the session is an httpOnly cookie.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";

import { fieldErrors, isMfaEnrollmentRequired, type Page } from "@/lib/api";
import { MFA_ENROLMENT_PATH } from "@/lib/mfa";
import { isSuperuser, usePermissions } from "@/lib/permissions";
import {
  createRole,
  listRoles,
  type Role,
  ROLE_CODES,
  rbacErrorMessage,
  suggestSlug,
} from "@/lib/rbac";

import { RoleBadges } from "./role-badges";

type Listing = { page: number; roles?: Page<Role>; error?: string };

const card = "w-full max-w-3xl space-y-4 rounded-xl border border-zinc-200 p-6 dark:border-zinc-800";
const input =
  "mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 dark:border-zinc-700 dark:bg-zinc-900";
const button =
  "rounded-md bg-zinc-900 px-3 py-2 text-sm text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900";

export function RolesPanel() {
  const router = useRouter();
  const perms = usePermissions();
  const allowed = perms.can(ROLE_CODES.view);
  const [page, setPage] = useState(1);
  const [listing, setListing] = useState<Listing | null>(null);

  useEffect(() => {
    if (!allowed) return;
    let active = true;
    listRoles(page)
      .then((roles) => {
        if (active) setListing({ page, roles });
      })
      .catch((error) => {
        if (!active) return;
        if (isMfaEnrollmentRequired(error)) router.push(MFA_ENROLMENT_PATH);
        setListing({ page, error: rbacErrorMessage(error) });
      });
    return () => {
      active = false;
    };
  }, [allowed, page, router]);

  if (perms.loading) return <p className="text-sm text-zinc-500">Checking your session…</p>;
  if (perms.failed) {
    return (
      <p role="alert" className="text-sm text-red-600">
        Could not reach the server. Reload the page to try again.
      </p>
    );
  }
  if (!perms.me) {
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

  const loading = !listing || listing.page !== page;
  const roles = listing?.roles;

  return (
    <div className="flex w-full flex-col items-center gap-6">
      <section className={card}>
        {loading ? (
          <p className="text-sm text-zinc-500">Loading roles…</p>
        ) : listing.error ? (
          <p role="alert" className="text-sm text-red-600">
            {listing.error}
          </p>
        ) : roles && roles.results.length > 0 ? (
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase tracking-wide text-zinc-500">
              <tr>
                <th className="pb-2 font-medium">Role</th>
                <th className="pb-2 font-medium">Permissions</th>
                <th className="pb-2 text-right font-medium">Users</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
              {roles.results.map((role) => (
                <tr key={role.public_id}>
                  <td className="py-2 pr-3">
                    <Link
                      className="font-medium underline"
                      href={`/settings/roles/${encodeURIComponent(role.public_id)}`}
                    >
                      {role.name}
                    </Link>{" "}
                    <RoleBadges role={role} />
                    <span className="block font-mono text-xs text-zinc-500">{role.slug}</span>
                  </td>
                  <td className="py-2 pr-3">{role.permissions.length}</td>
                  <td className="py-2 text-right">{role.user_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-sm text-zinc-500">No roles yet.</p>
        )}
        {roles && (roles.previous || roles.next) ? (
          <nav className="flex items-center justify-between text-sm">
            <button
              type="button"
              className="underline disabled:no-underline disabled:opacity-40"
              disabled={!roles.previous || loading}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
            >
              Previous
            </button>
            <span className="text-zinc-500">
              Page {page} · {roles.count} roles
            </span>
            <button
              type="button"
              className="underline disabled:no-underline disabled:opacity-40"
              disabled={!roles.next || loading}
              onClick={() => setPage((p) => p + 1)}
            >
              Next
            </button>
          </nav>
        ) : null}
      </section>

      {perms.can(ROLE_CODES.create) ? (
        <CreateRoleForm
          showElevated={isSuperuser(perms.me)}
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
      <span className="mt-1 block text-xs text-red-600">{fields[field].join(" ")}</span>
    ) : null;

  return (
    <form onSubmit={handleSubmit} className={card} noValidate>
      <h2 className="text-sm font-semibold">New role</h2>
      <p className="text-xs text-zinc-500">
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
        Slug <span className="text-xs text-zinc-500">(permanent: it cannot be changed later)</span>
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
        <p role="alert" className="text-sm text-red-600">
          {error}
        </p>
      ) : null}
      <button type="submit" disabled={pending} className={button}>
        {pending ? "Creating…" : "Create role"}
      </button>
    </form>
  );
}
