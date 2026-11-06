"use client";

/**
 * One user form, two modes (FRONTEND_PLATFORM § 11): no `user` creates (email + name; the API
 * emails a set-your-password link), a `user` edits (the name; the email is the sign-in identity and
 * is not editable here). As a page (/users/new) or a modal (from the index or the record).
 */
import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";

import { buttonClass } from "@/core/components/Button";
import { FormField } from "@/core/components/form/FormField";
import { INVITATION_CODES } from "@/core/lib/invitations";
import { usePermissions } from "@/core/lib/permissions";
import { useApiMutation } from "@/core/lib/query";
import { createUser, updateUser, type User } from "@/core/lib/users";
import { FormGrid, FormSection, ResourceForm } from "@/core/shells";

import { userLabel } from "./columns";
import { type UserCreateValues, userCreateSchema, type UserEditValues, userEditSchema } from "./fields";

type Common = { onSaved: (user: User) => void; layout?: "page" | "modal"; open?: boolean; onClose?: () => void };

export function UserForm(props: Common & { user?: User }) {
  return props.user ? <EditUserForm {...props} user={props.user} /> : <CreateUserForm {...props} />;
}

function CreateUserForm({ onSaved, layout = "page", open, onClose }: Common) {
  const perms = usePermissions();
  const form = useForm<UserCreateValues>({ resolver: zodResolver(userCreateSchema), defaultValues: { email: "", full_name: "" } });
  const create = useApiMutation({
    mutationFn: (values: UserCreateValues) => createUser(values.email, values.full_name),
    invalidates: ["users"],
  });
  return (
    <ResourceForm
      pageKey="users.user.form"
      form={form}
      resource="user"
      layout={layout}
      open={open}
      onClose={onClose}
      cancel={layout === "page" ? <Link href="/users" className={buttonClass("secondary")}>Cancel</Link> : undefined}
      intro={
        <>
          The account is created active, with no password: we email the address a link to set one. It holds no role until
          you assign one.
          {perms.can(INVITATION_CODES.send) ? (
            <>
              {" "}
              To give someone a role from the start,{" "}
              <Link className="underline" href="/users/invitations">
                send an invitation
              </Link>{" "}
              instead.
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
          <FormField control={form.control} name="email" kind="email" label="Email" required autoComplete="off" />
          <FormField control={form.control} name="full_name" kind="text" label="Full name" hint="Optional." autoComplete="off" />
        </FormGrid>
      </FormSection>
    </ResourceForm>
  );
}

function EditUserForm({ user, onSaved, layout = "modal", open, onClose }: Common & { user: User }) {
  const form = useForm<UserEditValues>({ resolver: zodResolver(userEditSchema), values: { full_name: user.full_name }, resetOptions: { keepDirtyValues: true } });
  const update = useApiMutation({
    mutationFn: (fullName: string) => updateUser(user.public_id, fullName),
    invalidates: ["users"],
  });
  return (
    <ResourceForm
      pageKey="users.user.form"
      form={form}
      resource="user"
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
        <FormField control={form.control} name="full_name" kind="text" label="Full name" autoComplete="off" />
      </FormSection>
    </ResourceForm>
  );
}

/** /users/new: the create form as a page; on save, the new record. */
export function UserCreatePage() {
  const router = useRouter();
  return <UserForm layout="page" onSaved={(user) => router.push(`/users/${encodeURIComponent(user.public_id)}`)} />;
}
