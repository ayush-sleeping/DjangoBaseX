"use client";

/** Send an invitation: an email and the role it starts with (a modal from the invitations index). */
import { zodResolver } from "@hookform/resolvers/zod";
import { useMemo } from "react";
import { useForm } from "react-hook-form";

import { FormField } from "@/core/components/form/FormField";
import { PanelError } from "@/core/components/PanelError";
import { toast } from "@/core/components/toast";
import { useT } from "@/core/lib/i18n";
import { sendInvitation } from "@/core/lib/invitations";
import { usePermissions } from "@/core/lib/permissions";
import { useApiMutation, useApiQuery } from "@/core/lib/query";
import { assignableBy, listAllRoles, type Role, ROLE_CODES, roleKeys } from "@/core/lib/rbac";
import { FormGrid, FormSection, ResourceForm } from "@/core/shells";

import { type InvitationValues, invitationSchema, useValidationCopy } from "./fields";

export function InvitationForm({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useT("users.invitations");
  const copy = useValidationCopy();
  const schema = useMemo(() => invitationSchema(copy), [copy]);
  const perms = usePermissions();
  const superuser = perms.user?.is_superuser === true;
  // The role picker reads GET /api/rbac/roles/, which needs rbac.roles.view.
  const canListRoles = perms.can(ROLE_CODES.view);
  const roles = useApiQuery<Role[]>(roleKeys.all(), (signal) => listAllRoles(20, signal), { enabled: canListRoles && open });
  const form = useForm<InvitationValues>({ resolver: zodResolver(schema), defaultValues: { email: "", role: "" } });
  const send = useApiMutation({ mutationFn: (v: InvitationValues) => sendInvitation(v.email, v.role), invalidates: ["users.invitations"] });
  // An elevated role can only be handed out by a superuser: don't offer it.
  const options = (roles.data ?? [])
    .filter((role) => assignableBy(role, superuser))
    .map((role) => ({ value: role.public_id, label: role.name, hint: role.is_elevated ? t("elevated") : undefined }));

  return (
    <ResourceForm
      pageKey="users.invitation.form"
      form={form}
      resource={t("resource")}
      layout="modal"
      open={open}
      onClose={onClose}
      submitLabel={t("send")}
      pendingLabel={t("sending")}
      onSubmit={async (values) => {
        await send.mutateAsync(values);
        toast(t("sent", { email: values.email }), { tone: "ok" });
        form.reset();
        onClose();
      }}
    >
      <FormSection>
        {!canListRoles ? (
          <p className="text-sm text-muted-foreground">{t("cannotListRoles")}</p>
        ) : roles.showError ? (
          <PanelError error={roles.error} retry={roles.refetch} what={t("rolesToGive")} />
        ) : (
          <FormGrid>
            <FormField control={form.control} name="email" kind="email" label={t("email")} required autoComplete="off" />
            <FormField control={form.control} name="role" kind="select" label={t("role")} required options={options} placeholder={roles.isLoading ? t("loadingRoles") : t("chooseRole")} />
          </FormGrid>
        )}
      </FormSection>
    </ResourceForm>
  );
}
