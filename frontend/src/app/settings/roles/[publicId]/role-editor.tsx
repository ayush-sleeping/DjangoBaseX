"use client";

// Client component: the role is authenticated data, and the session is an httpOnly cookie.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";

import { isMfaEnrollmentRequired } from "@/lib/api";
import { MFA_ENROLMENT_PATH } from "@/lib/mfa";
import { isSuperuser, type Permissions, usePermissions } from "@/lib/permissions";
import {
  deleteRole,
  fieldErrors,
  getRole,
  grantedIn,
  listPermissionGroups,
  type PermissionGroup,
  replaceRolePermissions,
  type Role,
  type RoleChanges,
  ROLE_CODES,
  rbacErrorMessage,
  updateRole,
} from "@/lib/rbac";

import { RoleBadges } from "../role-badges";

const card = "w-full max-w-3xl space-y-4 rounded-xl border border-zinc-200 p-6 dark:border-zinc-800";
const input =
  "mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 disabled:opacity-60 dark:border-zinc-700 dark:bg-zinc-900";
const button =
  "rounded-md bg-zinc-900 px-3 py-2 text-sm text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900";
const danger = "rounded-md bg-red-600 px-3 py-2 text-sm text-white disabled:opacity-50";

const SYSTEM_REASON =
  "This is a system role: its name, its permissions and its existence are fixed by the seed.";

type Loaded = {
  role: Role;
  /** Undefined when the user lacks rbac.permissions.view: grants then show as bare codes. */
  catalog?: PermissionGroup[];
};

type LoadState = { status: "loading" } | { status: "error"; message: string } | Loaded;

export function RoleEditor({ publicId }: { publicId: string }) {
  const router = useRouter();
  const perms = usePermissions();
  const allowed = perms.can(ROLE_CODES.view);
  const canSeeCatalog = perms.can(ROLE_CODES.viewCatalog);
  const [state, setState] = useState<LoadState>({ status: "loading" });

  useEffect(() => {
    if (!allowed) return;
    let active = true;
    Promise.all([getRole(publicId), canSeeCatalog ? listPermissionGroups() : undefined])
      .then(([role, catalog]) => {
        if (active) setState({ role, catalog });
      })
      .catch((error) => {
        if (!active) return;
        if (isMfaEnrollmentRequired(error)) router.push(MFA_ENROLMENT_PATH);
        setState({ status: "error", message: rbacErrorMessage(error) });
      });
    return () => {
      active = false;
    };
  }, [allowed, canSeeCatalog, publicId, router]);

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
  if (!allowed) return <p className="text-sm">You don&apos;t have permission to view roles.</p>;
  if ("status" in state) {
    return state.status === "loading" ? (
      <p className="text-sm text-zinc-500">Loading role…</p>
    ) : (
      <p role="alert" className="text-sm text-red-600">
        {state.message}
      </p>
    );
  }

  const { role, catalog } = state;
  // Every write answers with the new role; keep the catalog, which a write never changes.
  const replaceRole = (next: Role) => setState({ role: next, catalog });

  return (
    <div className="flex w-full flex-col items-center gap-6">
      <header className="w-full max-w-3xl space-y-1">
        <h1 className="text-2xl font-bold tracking-tight">
          {role.name} <RoleBadges role={role} />
        </h1>
        <p className="font-mono text-xs text-zinc-500">{role.slug}</p>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          Held by {role.user_count} user{role.user_count === 1 ? "" : "s"}.
        </p>
        {role.is_system ? <p className="text-sm text-zinc-500">🔒 {SYSTEM_REASON}</p> : null}
      </header>

      {perms.can(ROLE_CODES.update) ? (
        <DetailsForm key={role.public_id} role={role} perms={perms} onSaved={replaceRole} />
      ) : null}

      <GrantsSection
        key={role.public_id}
        role={role}
        catalog={catalog}
        editable={perms.can(ROLE_CODES.update) && !role.is_system && catalog !== undefined}
        onSaved={async () => replaceRole(await getRole(role.public_id))}
      />

      {perms.can(ROLE_CODES.delete) ? (
        <DeleteSection role={role} onDeleted={() => router.push("/settings/roles")} />
      ) : null}
    </div>
  );
}

function DetailsForm({
  role,
  perms,
  onSaved,
}: {
  role: Role;
  perms: Permissions;
  onSaved: (role: Role) => void;
}) {
  const superuser = isSuperuser(perms.me);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string }>();
  const [fields, setFields] = useState<Record<string, string[]>>({});

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    // Send only what changed: a PATCH carrying an unchanged name still trips the system-role rule.
    const changes: RoleChanges = {};
    const name = String(form.get("name") ?? "");
    const description = String(form.get("description") ?? "");
    const mfaRequired = form.get("mfa_required") === "on";
    if (!role.is_system && name !== role.name) changes.name = name;
    if (description !== role.description) changes.description = description;
    if (mfaRequired !== role.mfa_required) changes.mfa_required = mfaRequired;
    if (superuser) {
      const elevated = form.get("is_elevated") === "on";
      if (elevated !== role.is_elevated) changes.is_elevated = elevated;
    }
    if (Object.keys(changes).length === 0) {
      setMessage({ ok: true, text: "Nothing to save." });
      return;
    }
    setPending(true);
    try {
      onSaved(await updateRole(role.public_id, changes));
      setMessage({ ok: true, text: "Saved." });
      setFields({});
    } catch (error) {
      setMessage({ ok: false, text: rbacErrorMessage(error) });
      setFields(fieldErrors(error));
    } finally {
      setPending(false);
    }
  }

  const fieldError = (field: string) =>
    fields[field]?.length ? (
      <span className="mt-1 block text-xs text-red-600">{fields[field].join(" ")}</span>
    ) : null;

  return (
    <form onSubmit={handleSubmit} className={card} noValidate>
      <h2 className="text-sm font-semibold">Details</h2>
      <label className="block text-sm">
        Name
        <input
          name="name"
          defaultValue={role.name}
          disabled={role.is_system}
          required
          className={input}
        />
        {role.is_system ? (
          <span className="mt-1 block text-xs text-zinc-500">System roles keep their name.</span>
        ) : null}
        {fieldError("name")}
      </label>
      <label className="block text-sm">
        Description
        <textarea
          name="description"
          rows={2}
          defaultValue={role.description}
          className={input}
        />
        {fieldError("description")}
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" name="mfa_required" defaultChecked={role.mfa_required} />
        Require two-factor authentication for everyone holding this role
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          name="is_elevated"
          defaultChecked={role.is_elevated}
          disabled={!superuser}
        />
        Elevated: only a superuser can change or assign it
        {!superuser ? <span className="text-xs text-zinc-500">(superusers only)</span> : null}
      </label>
      {message ? (
        <p
          role={message.ok ? "status" : "alert"}
          className={`text-sm ${message.ok ? "text-zinc-500" : "text-red-600"}`}
        >
          {message.text}
        </p>
      ) : null}
      <button type="submit" disabled={pending} className={button}>
        {pending ? "Saving…" : "Save details"}
      </button>
    </form>
  );
}

function GrantsSection({
  role,
  catalog,
  editable,
  onSaved,
}: {
  role: Role;
  catalog?: PermissionGroup[];
  editable: boolean;
  onSaved: () => Promise<void>;
}) {
  const [selected, setSelected] = useState<Set<string>>(() => new Set(role.permissions));
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string }>();

  const original = new Set(role.permissions);
  const dirty =
    selected.size !== original.size || [...selected].some((code) => !original.has(code));

  function toggle(code: string, on: boolean) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (on) next.add(code);
      else next.delete(code);
      return next;
    });
    setMessage(undefined);
  }

  async function handleSave() {
    setPending(true);
    try {
      const diff = await replaceRolePermissions(role.public_id, [...selected]);
      setMessage({
        ok: true,
        text: `Saved: ${diff.added.length} granted, ${diff.removed.length} removed.`,
      });
      await onSaved();
    } catch (error) {
      setMessage({ ok: false, text: rbacErrorMessage(error) });
    } finally {
      setPending(false);
    }
  }

  return (
    <section className={card}>
      <h2 className="text-sm font-semibold">Permissions</h2>
      {role.is_system ? (
        <p className="text-xs text-zinc-500">🔒 System roles&apos; permissions are fixed.</p>
      ) : !editable ? (
        <p className="text-xs text-zinc-500">Read only.</p>
      ) : (
        <p className="text-xs text-zinc-500">
          Saving replaces the role&apos;s permissions with exactly the boxes ticked here.
        </p>
      )}

      {catalog ? (
        catalog.map((group) => (
          <fieldset key={group.code} className="space-y-1" disabled={!editable || pending}>
            <legend className="text-sm font-medium">
              {group.label}{" "}
              <span className="text-xs font-normal text-zinc-500">
                {grantedIn(group, selected)} of {group.permissions.length}
              </span>
            </legend>
            {group.permissions.map((permission) => {
              const checked = selected.has(permission.code);
              return (
                <label key={permission.code} className="flex items-baseline gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={checked}
                    // A deprecated permission can be removed but not newly granted.
                    disabled={permission.is_deprecated && !checked}
                    onChange={(event) => toggle(permission.code, event.target.checked)}
                  />
                  <span>
                    {permission.label}{" "}
                    <code className="text-xs text-zinc-500">{permission.code}</code>
                    {permission.is_deprecated ? (
                      <span className="ml-1 text-xs text-amber-600">deprecated</span>
                    ) : null}
                  </span>
                </label>
              );
            })}
          </fieldset>
        ))
      ) : role.permissions.length > 0 ? (
        <ul className="space-y-1 font-mono text-xs">
          {role.permissions.map((code) => (
            <li key={code}>{code}</li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-zinc-500">This role holds no permissions.</p>
      )}

      {message ? (
        <p
          role={message.ok ? "status" : "alert"}
          className={`text-sm ${message.ok ? "text-green-600" : "text-red-600"}`}
        >
          {message.text}
        </p>
      ) : null}
      {editable ? (
        <button type="button" onClick={handleSave} disabled={!dirty || pending} className={button}>
          {pending ? "Saving…" : "Save permissions"}
        </button>
      ) : null}
    </section>
  );
}

function DeleteSection({ role, onDeleted }: { role: Role; onDeleted: () => void }) {
  const [confirming, setConfirming] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string>();

  async function handleDelete() {
    setPending(true);
    try {
      await deleteRole(role.public_id);
      onDeleted();
    } catch (err) {
      setError(rbacErrorMessage(err));
      setPending(false);
    }
  }

  return (
    <section className={card}>
      <h2 className="text-sm font-semibold">Delete role</h2>
      {role.is_system ? (
        <p className="text-sm text-zinc-500">🔒 System roles cannot be deleted.</p>
      ) : role.user_count > 0 ? (
        <p className="text-sm text-zinc-500">
          {role.user_count} user{role.user_count === 1 ? "" : "s"} still hold this role. Remove it
          from them before deleting it.
        </p>
      ) : confirming ? (
        <div className="flex items-center gap-3">
          <button type="button" onClick={handleDelete} disabled={pending} className={danger}>
            {pending ? "Deleting…" : `Delete "${role.name}"`}
          </button>
          <button
            type="button"
            onClick={() => setConfirming(false)}
            className="text-sm text-zinc-500 underline"
          >
            Cancel
          </button>
        </div>
      ) : (
        <button type="button" onClick={() => setConfirming(true)} className={danger}>
          Delete this role
        </button>
      )}
      {error ? (
        <p role="alert" className="text-sm text-red-600">
          {error}
        </p>
      ) : null}
    </section>
  );
}
