"use client";

/**
 * One user form, two modes (FRONTEND_PLATFORM § 11): no `user` creates (email + name; the API
 * emails a set-your-password link), a `user` edits (the name; the email is the sign-in identity and
 * is not editable here). As a page (/users/new) or a modal (from the index or the record).
 */
import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo } from "react";
import { useForm } from "react-hook-form";

import { buttonClass } from "@/core/components/Button";
import { FormField } from "@/core/components/form/FormField";
import { useT } from "@/core/lib/i18n";
import { INVITATION_CODES } from "@/core/lib/invitations";
import { usePermissions } from "@/core/lib/permissions";
import { useApiMutation } from "@/core/lib/query";
import { createUser, updateUser, type User } from "@/core/lib/users";
import { FormGrid, FormSection, ResourceForm } from "@/core/shells";

import { userLabel } from "./columns";
import { type UserCreateValues, userCreateSchema, type UserEditValues, userEditSchema, useValidationCopy } from "./fields";

type Common = { onSaved: (user: User) => void; layout?: "page" | "modal"; open?: boolean; onClose?: () => void };

export function UserForm(props: Common & { user?: User }) {
  return props.user ? <EditUserForm {...props} user={props.user} /> : <CreateUserForm {...props} />;
}

function CreateUserForm({ onSaved, layout = "page", open, onClose }: Common) {
  const t = useT("users.form");
  const common = useT("common");
  const copy = useValidationCopy();
  const schema = useMemo(() => userCreateSchema(copy), [copy]);
  const perms = usePermissions();
  const form = useForm<UserCreateValues>({ resolver: zodResolver(schema), defaultValues: { email: "", full_name: "" } });
  const create = useApiMutation({
    mutationFn: (values: UserCreateValues) => createUser(values.email, values.full_name),
    invalidates: ["users"],
  });
  return (
    <ResourceForm
      pageKey="users.user.form"
      form={form}
      resource={t("resource")}
      layout={layout}
      open={open}
      onClose={onClose}
      cancel={layout === "page" ? <Link href="/users" className={buttonClass("secondary")}>{common("cancel")}</Link> : undefined}
      intro={
        <>
          {t("createIntro")}
          {perms.can(INVITATION_CODES.send) ? (
            <>
              {" "}
              {t.rich("inviteInstead", {
                link: (chunks) => (
                  <Link className="underline" href="/users/invitations">
                    {chunks}
                  </Link>
                ),
              })}
            </>
          ) : null}
        </>
      }
      onSubmit={async (values) => {
        const user = await create.mutateAsync(values);
        form.reset(values);
        onSaved(user);
      }}
    >
      <FormSection>
        <FormGrid>
          <FormField control={form.control} name="email" kind="email" label={t("email")} required autoComplete="off" />
          <FormField control={form.control} name="full_name" kind="text" label={t("fullName")} hint={t("optional")} autoComplete="off" />
        </FormGrid>
      </FormSection>
    </ResourceForm>
  );
}

function EditUserForm({ user, onSaved, layout = "modal", open, onClose }: Common & { user: User }) {
  const t = useT("users.form");
  const copy = useValidationCopy();
  const schema = useMemo(() => userEditSchema(copy), [copy]);
  const form = useForm<UserEditValues>({ resolver: zodResolver(schema), values: { full_name: user.full_name }, resetOptions: { keepDirtyValues: true } });
  const update = useApiMutation({
    mutationFn: (fullName: string) => updateUser(user.public_id, fullName),
    invalidates: ["users"],
  });
  return (
    <ResourceForm
      pageKey="users.user.form"
      form={form}
      resource={t("resource")}
      record={{ name: userLabel(user) }}
      layout={layout}
      open={open}
      onClose={onClose}
      onSubmit={async (_values, changed) => {
        // PATCH only what changed: the name is the one editable field today.
        const saved = await update.mutateAsync(changed.full_name ?? user.full_name);
        form.reset({ full_name: saved.full_name });
        onSaved(saved);
      }}
    >
      <FormSection>
        <FormField control={form.control} name="full_name" kind="text" label={t("fullName")} autoComplete="off" />
      </FormSection>
    </ResourceForm>
  );
}

/** /users/new: the create form as a page; on save, the new record. */
export function UserCreatePage() {
  const router = useRouter();
  return <UserForm layout="page" onSaved={(user) => router.push(`/users/${encodeURIComponent(user.public_id)}`)} />;
}
