"use client";

/** Send an invitation: an email and the role it starts with (a modal from the invitations index). */
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";

import { FormField } from "@/core/components/form/FormField";
import { PanelError } from "@/core/components/PanelError";
import { toast } from "@/core/components/toast";
import { sendInvitation } from "@/core/lib/invitations";
import { usePermissions } from "@/core/lib/permissions";
import { useApiMutation, useApiQuery } from "@/core/lib/query";
import { assignableBy, listAllRoles, type Role, ROLE_CODES, roleKeys } from "@/core/lib/rbac";
import { FormGrid, FormSection, ResourceForm } from "@/core/shells";

import { type InvitationValues, invitationSchema } from "./fields";

export function InvitationForm({ open, onClose }: { open: boolean; onClose: () => void }) {
  const perms = usePermissions();
  const superuser = perms.user?.is_superuser === true;
  // The role picker reads GET /api/rbac/roles/, which needs rbac.roles.view.
  const canListRoles = perms.can(ROLE_CODES.view);
  const roles = useApiQuery<Role[]>(roleKeys.all(), (signal) => listAllRoles(20, signal), { enabled: canListRoles && open });
  const form = useForm<InvitationValues>({ resolver: zodResolver(invitationSchema), defaultValues: { email: "", role: "" } });
  const send = useApiMutation({ mutationFn: (v: InvitationValues) => sendInvitation(v.email, v.role), invalidates: ["users.invitations"] });
  // An elevated role can only be handed out by a superuser: don't offer it.
  const options = (roles.data ?? [])
    .filter((role) => assignableBy(role, superuser))
    .map((role) => ({ value: role.public_id, label: role.name, hint: role.is_elevated ? "elevated" : undefined }));

  return (
    <ResourceForm
      pageKey="users.invitation.form"
      form={form}
      resource="invitation"
      layout="modal"
      open={open}
      onClose={onClose}
      submitLabel="Send invitation"
      pendingLabel="Sending…"
      onSubmit={async (values) => {
        await send.mutateAsync(values);
        toast(`Invitation sent to ${values.email}.`, { tone: "ok" });
        form.reset();
        onClose();
      }}
    >
      <FormSection>
        {!canListRoles ? (
          <p className="text-sm text-muted-foreground">Inviting needs a role to give, and you cannot list roles. Ask an administrator for the rbac.roles.view permission.</p>
        ) : roles.showError ? (
          <PanelError error={roles.error} retry={roles.refetch} what="the roles you can give" />
        ) : (
          <FormGrid>
            <FormField control={form.control} name="email" kind="email" label="Email" required autoComplete="off" />
            <FormField control={form.control} name="role" kind="select" label="Role" required options={options} placeholder={roles.isLoading ? "Loading roles…" : "Choose a role"} />
          </FormGrid>
        )}
      </FormSection>
    </ResourceForm>
  );
}
