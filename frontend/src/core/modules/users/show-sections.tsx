"use client";

/** The user record's sections. Each is an InfoCard; the layout is ResourceShow's. */
import { LogOut, Plus, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Button, IconButton } from "@/core/components/Button";
import { confirm } from "@/core/components/confirm";
import { PanelError } from "@/core/components/PanelError";
import { Select } from "@/core/components/Select";
import { toast } from "@/core/components/toast";
import { usePermissions } from "@/core/lib/permissions";
import { useApiMutation, useApiQuery } from "@/core/lib/query";
import { assignableBy, assignRole, listAllRoles, type Role, ROLE_CODES, rbacErrorMessage, roleKeys, unassignRole } from "@/core/lib/rbac";
import { revokeUserSessions, type User, usersErrorMessage } from "@/core/lib/users";
import { InfoCard } from "@/core/shells";

import { USER_ACTIONS } from "./actions";
import { userLabel } from "./columns";

export function RolesCard({ user }: { user: User }) {
  const perms = usePermissions();
  const superuser = perms.user?.is_superuser === true;
  // Assigning needs the right to assign AND to list roles to pick from.
  const canAssign = perms.can(USER_ACTIONS.assignRole.permission) && perms.can(ROLE_CODES.view);
  const catalog = useApiQuery<Role[]>(roleKeys.all(), (signal) => listAllRoles(20, signal), { enabled: canAssign });
  const [chosen, setChosen] = useState<string | null>(null);
  const change = useApiMutation({
    mutationFn: async (action: { assign: boolean; role: string }) => {
      if (action.assign) await assignRole(user.public_id, action.role);
      else await unassignRole(user.public_id, action.role);
    },
    invalidates: ["users", "rbac.roles"],
  });

  const byId = new Map((catalog.data ?? []).map((role) => [role.public_id, role]));
  const held = new Set(user.roles.map((role) => role.public_id));
  // An elevated role needs a superuser to assign or revoke; one missing from the catalog goes to the API.
  const mayChange = (id: string) => (byId.has(id) ? assignableBy(byId.get(id)!, superuser) : true);
  const offered = (catalog.data ?? []).filter((role) => !held.has(role.public_id) && assignableBy(role, superuser));
  const selected = chosen && offered.some((r) => r.public_id === chosen) ? chosen : (offered[0]?.public_id ?? null);

  async function run(action: { assign: boolean; role: string }, name: string) {
    if (!action.assign && !(await confirm({ title: `Remove ${name} from ${userLabel(user)}?`, confirmLabel: "Remove", tone: "danger" }))) return;
    try {
      await change.mutateAsync(action);
      toast(action.assign ? `${name} assigned.` : `${name} removed.`, { tone: "ok" });
    } catch (error) {
      toast(rbacErrorMessage(error), { tone: "err" });
    }
  }

  return (
    <InfoCard title="Roles">
      {user.roles.length === 0 ? (
        <p className="text-sm text-muted-foreground">No roles. This user can sign in and see nothing else.</p>
      ) : (
        <ul className="divide-y divide-border text-sm">
          {user.roles.map((role) => (
            <li key={role.public_id} className="flex items-center justify-between gap-3 py-1.5">
              {perms.can(ROLE_CODES.view) ? (
                <Link className="underline-offset-4 hover:underline" href={`/settings/roles/${encodeURIComponent(role.public_id)}`}>
                  {role.name}
                </Link>
              ) : (
                <span>{role.name}</span>
              )}
              {canAssign && mayChange(role.public_id) ? (
                <IconButton icon={X} label={`Remove ${role.name}`} disabled={change.isPending} onClick={() => void run({ assign: false, role: role.public_id }, role.name)} />
              ) : canAssign ? (
                <span className="text-xs text-muted-foreground">Superusers only</span>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {canAssign ? (
        catalog.showError ? (
          <PanelError error={catalog.error} retry={catalog.refetch} what="the roles you can assign" />
        ) : catalog.isLoading ? (
          <p className="text-xs text-muted-foreground">Loading roles…</p>
        ) : offered.length > 0 && selected ? (
          <div className="flex gap-2">
            <div className="min-w-0 flex-1">
              <Select
                label="Role to assign"
                options={offered.map((role) => ({ value: role.public_id, label: role.name, hint: role.is_elevated ? "elevated" : undefined }))}
                value={selected}
                onChange={setChosen}
              />
            </div>
            <Button onClick={() => void run({ assign: true, role: selected }, byId.get(selected)?.name ?? "Role")} pending={change.isPending} pendingLabel="Assigning…">
              <Plus aria-hidden className="size-4" /> Assign
            </Button>
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">No other role you can assign.</p>
        )
      ) : null}
    </InfoCard>
  );
}

export function SessionsCard({ user, self, onSignedOutSelf }: { user: User; self: boolean; onSignedOutSelf: () => void }) {
  const revoke = useApiMutation({
    mutationFn: () => revokeUserSessions(user.public_id),
    invalidates: [],
    reason: "Sessions are not cached on the client; nothing shown changes.",
  });

  async function handleRevoke() {
    const ok = await confirm({
      title: self ? "Sign out all your sessions?" : `Sign ${userLabel(user)} out everywhere?`,
      body: self ? "That includes this browser: you will sign in again." : "Anyone signed in as them must sign in again.",
      confirmLabel: "Sign out everywhere",
      tone: "danger",
    });
    if (!ok) return;
    try {
      const count = await revoke.mutateAsync();
      if (self) return onSignedOutSelf();
      toast(`Signed out of ${count} session${count === 1 ? "" : "s"}.`, { tone: "ok" });
    } catch (error) {
      toast(usersErrorMessage(error), { tone: "err" });
    }
  }

  return (
    <InfoCard
      title="Sessions"
      actions={
        <Button variant="secondary" size="sm" onClick={() => void handleRevoke()} pending={revoke.isPending} pendingLabel="Signing out…">
          <LogOut aria-hidden className="size-4" /> Sign out everywhere
        </Button>
      }
    >
      <p className="text-sm text-muted-foreground">
        Signs {self ? "you" : "this user"} out on every device{self ? ", this browser included" : ""}.
      </p>
    </InfoCard>
  );
}
