"use client";

/** The user record (BUILD_ORDER 8.3b reference module): composes ResourceShow only. */
import { Pencil, UserCheck, UserX } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/core/components/Button";
import { confirm } from "@/core/components/confirm";
import { DateTime } from "@/core/components/format";
import { StatusPill } from "@/core/components/StatusPill";
import { toast } from "@/core/components/toast";
import { usePermissions } from "@/core/lib/permissions";
import { useApiMutation, useApiQuery } from "@/core/lib/query";
import { activateUser, getUser, type User, usersErrorMessage } from "@/core/lib/users";
import { MetaCard, ResourceShow } from "@/core/shells";

import { USER_ACTIONS } from "./actions";
import { userLabel } from "./columns";
import { DeactivateForm } from "./DeactivateForm";
import { UserForm } from "./Form";
import { userKeys } from "./keys";
import { RolesCard, SessionsCard } from "./show-sections";

export function UserShow({ publicId }: { publicId: string }) {
  const router = useRouter();
  const perms = usePermissions();
  const query = useApiQuery<User>(userKeys.detail(publicId), (signal) => getUser(publicId, signal));
  const [editing, setEditing] = useState(false);
  const [deactivating, setDeactivating] = useState(false);
  const activate = useApiMutation({ mutationFn: () => activateUser(publicId), invalidates: ["users"] });
  const user = query.data;
  const self = perms.user?.public_id === publicId;

  async function handleActivate() {
    if (!user || !(await confirm({ title: `Activate ${userLabel(user)}?`, body: "They can sign in again.", confirmLabel: "Activate" }))) return;
    try {
      await activate.mutateAsync();
      toast("Account activated.", { tone: "ok" });
    } catch (error) {
      toast(usersErrorMessage(error), { tone: "err" });
    }
  }

  return (
    <ResourceShow
      pageKey="users.user.show"
      noun="user"
      state={{ isLoading: query.isLoading, showError: query.showError, error: query.error, refetch: query.refetch }}
      title={user?.email}
      subtitle={user ? [user.full_name, self ? "This is your account." : ""].filter(Boolean).join(" · ") : undefined}
      badges={
        user ? (
          <>
            <StatusPill status={user.is_active ? "users.user.active" : "users.user.deactivated"} />
            {user.is_superuser ? <StatusPill status="users.user.superuser" title="Bypasses every permission check." /> : null}
            {user.mfa_enabled ? <StatusPill status="users.user.mfa_on" /> : null}
          </>
        ) : null
      }
      actions={
        user ? (
          <>
            {perms.can(USER_ACTIONS.edit.permission) ? (
              <Button variant="secondary" onClick={() => setEditing(true)}>
                <Pencil aria-hidden className="size-4" /> Edit
              </Button>
            ) : null}
            {perms.can(USER_ACTIONS.deactivate.permission) && !self ? (
              user.is_active ? (
                <Button variant="destructive" onClick={() => setDeactivating(true)}>
                  <UserX aria-hidden className="size-4" /> Deactivate
                </Button>
              ) : (
                <Button onClick={() => void handleActivate()} pending={activate.isPending} pendingLabel="Activating…">
                  <UserCheck aria-hidden className="size-4" /> Activate
                </Button>
              )
            ) : null}
          </>
        ) : null
      }
      sidebar={
        user ? (
          <MetaCard
            items={[
              { label: "Created", value: <DateTime value={user.created_at} /> },
              { label: "Last sign-in", value: <DateTime value={user.last_login} /> },
              ...(user.is_active
                ? []
                : [
                    {
                      label: "Deactivated",
                      value: (
                        <>
                          <DateTime value={user.deactivated_at} />
                          {user.deactivated_reason ? ` — ${user.deactivated_reason}` : ""}
                        </>
                      ),
                    },
                  ]),
            ]}
          />
        ) : null
      }
    >
      {user ? (
        <>
          <RolesCard user={user} />
          {perms.can(USER_ACTIONS.revokeSessions.permission) ? <SessionsCard user={user} self={self} onSignedOutSelf={() => router.push("/login")} /> : null}
          {editing ? <UserForm user={user} layout="modal" open onClose={() => setEditing(false)} onSaved={() => setEditing(false)} /> : null}
          {deactivating ? <DeactivateForm user={user} onClose={() => setDeactivating(false)} /> : null}
        </>
      ) : null}
    </ResourceShow>
  );
}
