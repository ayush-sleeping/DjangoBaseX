"use client";

/** Invitations (BUILD_ORDER 8.3b reference module): composes ResourceIndex only. */
import { Send } from "lucide-react";
import { useState } from "react";

import { Button } from "@/core/components/Button";
import { confirm } from "@/core/components/confirm";
import { toast } from "@/core/components/toast";
import { type Invitation, invitationErrorMessage, listInvitations, revokeInvitation } from "@/core/lib/invitations";
import { useT } from "@/core/lib/i18n";
import { useListState } from "@/core/lib/list-state";
import { usePermissions } from "@/core/lib/permissions";
import { useApiList, useApiMutation } from "@/core/lib/query";
import { ResourceIndex } from "@/core/shells";

import { USER_ACTIONS } from "./actions";
import { useInvitationColumns } from "./columns";
import { InvitationForm } from "./InvitationForm";
import { invitationKeys } from "./keys";

const getRowId = (i: Invitation) => i.public_id;
const getRowLabel = (i: Invitation) => i.email;

export function InvitationsIndex() {
  const t = useT("users.invitations");
  const perms = usePermissions();
  const state = useListState();
  const [sending, setSending] = useState(false);
  const query = { page: state.page };
  const list = useApiList<Invitation>(invitationKeys.list(query), (signal) => listInvitations(query.page, signal));
  const revoke = useApiMutation({ mutationFn: (i: Invitation) => revokeInvitation(i.public_id), invalidates: ["users.invitations"] });
  const canInvite = perms.can(USER_ACTIONS.invite.permission);

  async function handleRevoke(invitation: Invitation) {
    const ok = await confirm({
      title: t("revokeTitle", { email: invitation.email }),
      body: t("revokeBody"),
      confirmLabel: t("revoke"),
      tone: "danger",
    });
    if (!ok) return;
    try {
      await revoke.mutateAsync(invitation);
      toast(t("revoked"), { tone: "ok" });
    } catch (error) {
      toast(invitationErrorMessage(error), { tone: "err" });
    }
  }

  const send = canInvite ? (
    <Button onClick={() => setSending(true)}>
      <Send aria-hidden className="size-4" /> {t("send")}
    </Button>
  ) : null;
  const columns = useInvitationColumns({
    onRevoke: perms.can(USER_ACTIONS.revokeInvitation.permission) ? (i) => void handleRevoke(i) : undefined,
    revoking: revoke.isPending ? revoke.variables?.public_id : undefined,
  });

  return (
    <ResourceIndex<Invitation>
      pageKey="users.invitation.index"
      title={t("title")}
      noun={t("noun")}
      description={t("description")}
      actions={send}
      columns={columns}
      list={list}
      getRowId={getRowId}
      getRowLabel={getRowLabel}
      page={state.page}
      onPage={state.setPage}
      queryIdentity="all"
      filtered={false}
      emptyAction={send}
    >
      {canInvite ? <InvitationForm open={sending} onClose={() => setSending(false)} /> : null}
    </ResourceIndex>
  );
}
