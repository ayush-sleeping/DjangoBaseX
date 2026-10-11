"use client";

// Client component: the user is authenticated data, and the session is an httpOnly cookie.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";

import { fieldErrors, isMfaEnrollmentRequired } from "@/lib/api";
import { MFA_ENROLMENT_PATH } from "@/lib/mfa";
import { isSuperuser, type Permissions, usePermissions } from "@/lib/permissions";
import {
  assignableBy,
  assignRole,
  listAllRoles,
  type Role,
  ROLE_CODES,
  rbacErrorMessage,
  unassignRole,
} from "@/lib/rbac";
import {
  activateUser,
  deactivateUser,
  formatDateTime,
  getUser,
  revokeUserSessions,
  updateUser,
  type User,
  USER_CODES,
  usersErrorMessage,
} from "@/lib/users";

import { Gate, ui, UserBadges } from "../gate";

type LoadState = { status: "loading" } | { status: "error"; message: string } | { user: User };

export function UserDetail({ publicId }: { publicId: string }) {
  const router = useRouter();
  const perms = usePermissions();
  const allowed = perms.can(USER_CODES.view);
  const [state, setState] = useState<LoadState>({ status: "loading" });

  useEffect(() => {
    if (!allowed) return;
    let active = true;
    getUser(publicId)
      .then((user) => {
        if (active) setState({ user });
      })
      .catch((error) => {
        if (!active) return;
        if (isMfaEnrollmentRequired(error)) router.push(MFA_ENROLMENT_PATH);
        setState({ status: "error", message: usersErrorMessage(error) });
      });
    return () => {
      active = false;
    };
  }, [allowed, publicId, router]);

  return (
    <Gate perms={perms} code={USER_CODES.view} what="view users">
      {(me) => {
        if ("status" in state) {
          return state.status === "loading" ? (
            <p className="text-sm text-zinc-500">Loading user…</p>
          ) : (
            <p role="alert" className={ui.error}>
              {state.message}
            </p>
          );
        }
        const { user } = state;
        const setUser = (next: User) => setState({ user: next });
        const self = me.public_id === user.public_id;
        return (
          <div className="flex w-full flex-col items-center gap-6">
            <Header user={user} self={self} />
            {perms.can(USER_CODES.update) ? <NameForm user={user} onSaved={setUser} /> : null}
            <RolesSection user={user} perms={perms} onChanged={setUser} />
            {perms.can(USER_CODES.revokeSessions) ? (
              <SessionsSection
                user={user}
                self={self}
                onSignedOutSelf={() => router.push("/login")}
              />
            ) : null}
            {perms.can(USER_CODES.deactivate) ? (
              <StatusSection user={user} self={self} onChanged={setUser} />
            ) : null}
          </div>
        );
      }}
    </Gate>
  );
}

function Header({ user, self }: { user: User; self: boolean }) {
  return (
    <header className="w-full max-w-3xl space-y-1">
      <h1 className="text-2xl font-bold tracking-tight">
        {user.email} <UserBadges user={user} />
      </h1>
      {user.full_name ? <p className="text-sm">{user.full_name}</p> : null}
      {self ? <p className="text-xs text-zinc-500">This is your account.</p> : null}
      <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 pt-2 text-xs text-zinc-500">
        <dt>Created</dt>
        <dd>{formatDateTime(user.created_at)}</dd>
        <dt>Last sign-in</dt>
        <dd>{formatDateTime(user.last_login)}</dd>
        {user.is_active ? null : (
          <>
            <dt>Deactivated</dt>
            <dd>
              {formatDateTime(user.deactivated_at)}
              {user.deactivated_reason ? ` — ${user.deactivated_reason}` : ""}
            </dd>
          </>
        )}
      </dl>
    </header>
  );
}

function NameForm({ user, onSaved }: { user: User; onSaved: (user: User) => void }) {
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string }>();
  const [fields, setFields] = useState<Record<string, string[]>>({});

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fullName = String(new FormData(event.currentTarget).get("full_name") ?? "");
    if (fullName === user.full_name) {
      setMessage({ ok: true, text: "Nothing to save." });
      return;
    }
    setPending(true);
    try {
      onSaved(await updateUser(user.public_id, fullName));
      setMessage({ ok: true, text: "Saved." });
      setFields({});
    } catch (error) {
      setMessage({ ok: false, text: usersErrorMessage(error) });
      setFields(fieldErrors(error));
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className={ui.card} noValidate>
      <h2 className="text-sm font-semibold">Name</h2>
      <label className="block text-sm">
        Full name
        <input name="full_name" defaultValue={user.full_name} className={ui.input} />
        {fields.full_name?.length ? (
          <span className="mt-1 block text-xs text-red-600">{fields.full_name.join(" ")}</span>
        ) : null}
      </label>
      {message ? (
        <p role={message.ok ? "status" : "alert"} className={message.ok ? "text-sm" : ui.error}>
          {message.text}
        </p>
      ) : null}
      <button type="submit" disabled={pending} className={ui.button}>
        {pending ? "Saving…" : "Save name"}
      </button>
    </form>
  );
}

function RolesSection({
  user,
  perms,
  onChanged,
}: {
  user: User;
  perms: Permissions;
  onChanged: (user: User) => void;
}) {
  const superuser = isSuperuser(perms.me);
  // Assigning needs the right to assign AND to list roles to pick from.
  const canAssign = perms.can(ROLE_CODES.assign) && perms.can(ROLE_CODES.view);
  const [catalog, setCatalog] = useState<Role[] | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string>();

  useEffect(() => {
    if (!canAssign) return;
    let active = true;
    listAllRoles()
      .then((roles) => {
        if (active) setCatalog(roles);
      })
      .catch((err) => {
        if (active) setError(rbacErrorMessage(err));
      });
    return () => {
      active = false;
    };
  }, [canAssign]);

  const byId = new Map((catalog ?? []).map((role) => [role.public_id, role]));
  const held = new Set(user.roles.map((role) => role.public_id));
  // An elevated role needs a superuser to assign or revoke (§ 8.2); unknown ones go to the API.
  const mayChange = (publicId: string) => {
    const role = byId.get(publicId);
    return role ? assignableBy(role, superuser) : true;
  };
  const offered = (catalog ?? []).filter(
    (role) => !held.has(role.public_id) && assignableBy(role, superuser),
  );

  async function change(action: () => Promise<unknown>) {
    setPending(true);
    setError(undefined);
    try {
      await action();
      onChanged(await getUser(user.public_id));
    } catch (err) {
      setError(rbacErrorMessage(err));
    } finally {
      setPending(false);
    }
  }

  function handleAssign(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const rolePublicId = String(new FormData(event.currentTarget).get("role") ?? "");
    if (rolePublicId) void change(() => assignRole(user.public_id, rolePublicId));
  }

  return (
    <section className={ui.card}>
      <h2 className="text-sm font-semibold">Roles</h2>
      {user.roles.length === 0 ? (
        <p className="text-sm text-zinc-500">
          No roles. This user can sign in and see nothing else.
        </p>
      ) : (
        <ul className="divide-y divide-zinc-200 text-sm dark:divide-zinc-800">
          {user.roles.map((role) => (
            <li key={role.public_id} className="flex items-center justify-between py-1.5">
              {perms.can(ROLE_CODES.view) ? (
                <Link
                  className="underline"
                  href={`/settings/roles/${encodeURIComponent(role.public_id)}`}
                >
                  {role.name}
                </Link>
              ) : (
                <span>{role.name}</span>
              )}
              {canAssign && mayChange(role.public_id) ? (
                <button
                  type="button"
                  disabled={pending}
                  onClick={() => change(() => unassignRole(user.public_id, role.public_id))}
                  className={ui.quiet}
                >
                  Remove
                </button>
              ) : canAssign ? (
                <span className="text-xs text-zinc-500" title="Elevated role">
                  🔒 superusers only
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {canAssign ? (
        catalog === null ? (
          error ? null : <p className="text-xs text-zinc-500">Loading roles…</p>
        ) : offered.length > 0 ? (
          <form onSubmit={handleAssign} className="flex gap-2">
            <select name="role" aria-label="Role to assign" className={`${ui.input} mt-0`}>
              {offered.map((role) => (
                <option key={role.public_id} value={role.public_id}>
                  {role.name}
                  {role.is_elevated ? " (elevated)" : ""}
                </option>
              ))}
            </select>
            <button type="submit" disabled={pending} className={ui.button}>
              Assign
            </button>
          </form>
        ) : (
          <p className="text-xs text-zinc-500">No other role you can assign.</p>
        )
      ) : null}
      {error ? (
        <p role="alert" className={ui.error}>
          {error}
        </p>
      ) : null}
    </section>
  );
}

function SessionsSection({
  user,
  self,
  onSignedOutSelf,
}: {
  user: User;
  self: boolean;
  onSignedOutSelf: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string }>();

  async function handleRevoke() {
    setPending(true);
    try {
      const count = await revokeUserSessions(user.public_id);
      if (self) {
        onSignedOutSelf();
        return;
      }
      setMessage({ ok: true, text: `Signed out of ${count} session${count === 1 ? "" : "s"}.` });
      setConfirming(false);
    } catch (error) {
      setMessage({ ok: false, text: usersErrorMessage(error) });
    } finally {
      setPending(false);
    }
  }

  return (
    <section className={ui.card}>
      <h2 className="text-sm font-semibold">Sessions</h2>
      <p className="text-sm">
        Signs {self ? "you" : "this user"} out on every device. Anyone signed in as{" "}
        {self ? "you" : "them"} must sign in again.
        {self ? " That includes this browser." : ""}
      </p>
      {confirming ? (
        <div className="flex items-center gap-3">
          <button type="button" onClick={handleRevoke} disabled={pending} className={ui.danger}>
            {pending ? "Signing out…" : "Sign out everywhere"}
          </button>
          <button type="button" onClick={() => setConfirming(false)} className={ui.quiet}>
            Cancel
          </button>
        </div>
      ) : (
        <button type="button" onClick={() => setConfirming(true)} className={ui.button}>
          {self ? "Sign out all your sessions" : "Sign out all their sessions"}
        </button>
      )}
      {message ? (
        <p role={message.ok ? "status" : "alert"} className={message.ok ? "text-sm" : ui.error}>
          {message.text}
        </p>
      ) : null}
    </section>
  );
}

function StatusSection({
  user,
  self,
  onChanged,
}: {
  user: User;
  self: boolean;
  onChanged: (user: User) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string>();

  async function run(action: () => Promise<User>) {
    setPending(true);
    setError(undefined);
    try {
      onChanged(await action());
      setConfirming(false);
    } catch (err) {
      setError(usersErrorMessage(err));
    } finally {
      setPending(false);
    }
  }

  function handleDeactivate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const reason = String(new FormData(event.currentTarget).get("reason") ?? "");
    void run(() => deactivateUser(user.public_id, reason));
  }

  return (
    <section className={ui.card}>
      <h2 className="text-sm font-semibold">{user.is_active ? "Deactivate" : "Activate"}</h2>
      {!user.is_active ? (
        <>
          <p className="text-sm">This account cannot sign in. Activating it lets it sign in again.</p>
          <button
            type="button"
            onClick={() => run(() => activateUser(user.public_id))}
            disabled={pending}
            className={ui.button}
          >
            {pending ? "Activating…" : "Activate account"}
          </button>
        </>
      ) : self ? (
        // The API answers 409 self_deactivation: say so instead of offering the button.
        <p className="text-sm text-zinc-500">You cannot deactivate your own account.</p>
      ) : confirming ? (
        <form onSubmit={handleDeactivate} className="space-y-3" noValidate>
          <label className="block text-sm">
            Reason <span className="text-xs text-zinc-500">(kept with the account)</span>
            <textarea name="reason" rows={2} className={ui.input} />
          </label>
          <div className="flex items-center gap-3">
            <button type="submit" disabled={pending} className={ui.danger}>
              {pending ? "Deactivating…" : "Deactivate and sign out everywhere"}
            </button>
            <button type="button" onClick={() => setConfirming(false)} className={ui.quiet}>
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <>
          <p className="text-sm">
            A deactivated account cannot sign in, and every session it has is signed out at once.
            Nothing is deleted; you can activate it again.
          </p>
          <button type="button" onClick={() => setConfirming(true)} className={ui.danger}>
            Deactivate account
          </button>
        </>
      )}
      {error ? (
        <p role="alert" className={ui.error}>
          {error}
        </p>
      ) : null}
    </section>
  );
}
