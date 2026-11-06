"use client";

/** Deactivating asks for a reason, kept with the account: a small form, so it is a ResourceForm. */
import { zodResolver } from "@hookform/resolvers/zod";
import { useMemo } from "react";
import { useForm } from "react-hook-form";

import { FormField } from "@/core/components/form/FormField";
import { toast } from "@/core/components/toast";
import { useT } from "@/core/lib/i18n";
import { useApiMutation } from "@/core/lib/query";
import { deactivateUser, type User } from "@/core/lib/users";
import { FormSection, ResourceForm } from "@/core/shells";

import { userLabel } from "./columns";
import { type DeactivateValues, deactivateSchema, useValidationCopy } from "./fields";

export function DeactivateForm({ user, onClose }: { user: User; onClose: () => void }) {
  const t = useT("users.deactivate");
  const formCopy = useT("users.form");
  const copy = useValidationCopy();
  const schema = useMemo(() => deactivateSchema(copy), [copy]);
  const form = useForm<DeactivateValues>({ resolver: zodResolver(schema), defaultValues: { reason: "" } });
  const deactivate = useApiMutation({ mutationFn: (reason: string) => deactivateUser(user.public_id, reason), invalidates: ["users"] });
  return (
    <ResourceForm
      pageKey="users.user.deactivate"
      form={form}
      resource={formCopy("resource")}
      record={{ name: userLabel(user) }}
      layout="modal"
      open
      onClose={onClose}
      submitLabel={t("submit")}
      pendingLabel={t("pending")}
      intro={t("intro")}
      onSubmit={async (values) => {
        await deactivate.mutateAsync(values.reason);
        toast(t("done"), { tone: "ok" });
        onClose();
      }}
    >
      <FormSection>
        <FormField control={form.control} name="reason" kind="textarea" label={t("reason")} hint={t("reasonHint")} />
      </FormSection>
    </ResourceForm>
  );
}
