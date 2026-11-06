"use client";

/** Deactivating asks for a reason, kept with the account: a small form, so it is a ResourceForm. */
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";

import { FormField } from "@/core/components/form/FormField";
import { toast } from "@/core/components/toast";
import { useApiMutation } from "@/core/lib/query";
import { deactivateUser, type User } from "@/core/lib/users";
import { FormSection, ResourceForm } from "@/core/shells";

import { userLabel } from "./columns";
import { type DeactivateValues, deactivateSchema } from "./fields";

export function DeactivateForm({ user, onClose }: { user: User; onClose: () => void }) {
  const form = useForm<DeactivateValues>({ resolver: zodResolver(deactivateSchema), defaultValues: { reason: "" } });
  const deactivate = useApiMutation({ mutationFn: (reason: string) => deactivateUser(user.public_id, reason), invalidates: ["users"] });
  return (
    <ResourceForm
      pageKey="users.user.deactivate"
      form={form}
      resource="user"
      record={{ name: userLabel(user) }}
      layout="modal"
      open
      onClose={onClose}
      submitLabel="Deactivate and sign out everywhere"
      pendingLabel="Deactivating…"
      intro="A deactivated account cannot sign in, and every session it has is signed out at once. Nothing is deleted; you can activate it again."
      onSubmit={async (values) => {
        await deactivate.mutateAsync(values.reason);
        toast("Account deactivated.", { tone: "ok" });
        onClose();
      }}
    >
      <FormSection>
        <FormField control={form.control} name="reason" kind="textarea" label="Reason" hint="Kept with the account." />
      </FormSection>
    </ResourceForm>
  );
}
