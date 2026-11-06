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
import { useT } from "@/core/lib/i18n";
import { usePermissions } from "@/core/lib/permissions";
import { useApiMutation, useApiQuery } from "@/core/lib/query";
import { assignableBy, assignRole, listAllRoles, type Role, ROLE_CODES, rbacErrorMessage, roleKeys, unassignRole } from "@/core/lib/rbac";
import { revokeUserSessions, type User, usersErrorMessage } from "@/core/lib/users";
import { InfoCard } from "@/core/shells";

import { USER_ACTIONS } from "./actions";
import { userLabel } from "./columns";

export function RolesCard({ user }: { user: User }) {
  const t = useT("users.roles");
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
    if (!action.assign && !(await confirm({ title: t("removeTitle", { role: name, name: userLabel(user) }), confirmLabel: t("removeConfirm"), tone: "danger" }))) return;
    try {
      await change.mutateAsync(action);
      toast(action.assign ? t("assigned", { role: name }) : t("removed", { role: name }), { tone: "ok" });
    } catch (error) {
      toast(rbacErrorMessage(error), { tone: "err" });
    }
  }

  return (
    <InfoCard title={t("title")}>
      {user.roles.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("none")}</p>
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
                <IconButton icon={X} label={t("remove", { role: role.name })} disabled={change.isPending} onClick={() => void run({ assign: false, role: role.public_id }, role.name)} />
              ) : canAssign ? (
                <span className="text-xs text-muted-foreground">{t("superusersOnly")}</span>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {canAssign ? (
        catalog.showError ? (
          <PanelError error={catalog.error} retry={catalog.refetch} what={t("rolesToAssign")} />
        ) : catalog.isLoading ? (
          <p className="text-xs text-muted-foreground">{t("loading")}</p>
        ) : offered.length > 0 && selected ? (
          <div className="flex gap-2">
            <div className="min-w-0 flex-1">
              <Select
                label={t("toAssign")}
                options={offered.map((role) => ({ value: role.public_id, label: role.name, hint: role.is_elevated ? t("elevated") : undefined }))}
                value={selected}
                onChange={setChosen}
              />
            </div>
            <Button onClick={() => void run({ assign: true, role: selected }, byId.get(selected)?.name ?? selected)} pending={change.isPending} pendingLabel={t("assigning")}>
              <Plus aria-hidden className="size-4" /> {t("assign")}
            </Button>
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">{t("noneToAssign")}</p>
        )
      ) : null}
    </InfoCard>
  );
}

export function SessionsCard({ user, self, onSignedOutSelf }: { user: User; self: boolean; onSignedOutSelf: () => void }) {
  const t = useT("users.sessions");
  const revoke = useApiMutation({
    mutationFn: () => revokeUserSessions(user.public_id),
    invalidates: [],
    reason: "Sessions are not cached on the client; nothing shown changes.",
  });

  async function handleRevoke() {
    const ok = await confirm({
      title: self ? t("selfTitle") : t("otherTitle", { name: userLabel(user) }),
      body: self ? t("selfBody") : t("otherBody"),
      confirmLabel: t("signOutEverywhere"),
      tone: "danger",
    });
    if (!ok) return;
    try {
      const count = await revoke.mutateAsync();
      if (self) return onSignedOutSelf();
      toast(t("signedOut", { count }), { tone: "ok" });
    } catch (error) {
      toast(usersErrorMessage(error), { tone: "err" });
    }
  }

  return (
    <InfoCard
      title={t("title")}
      actions={
        <Button variant="secondary" size="sm" onClick={() => void handleRevoke()} pending={revoke.isPending} pendingLabel={t("signingOut")}>
          <LogOut aria-hidden className="size-4" /> {t("signOutEverywhere")}
        </Button>
      }
    >
      <p className="text-sm text-muted-foreground">{self ? t("explainSelf") : t("explainOther")}</p>
    </InfoCard>
  );
}
