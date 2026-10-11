"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { fieldErrors } from "@/core/lib/api";
import { INVITATION_CODES } from "@/core/lib/invitations";
import { usePermissions } from "@/core/lib/permissions";
import { createUser, USER_CODES, usersErrorMessage } from "@/core/lib/users";

import { Gate, ui } from "../gate";

export function NewUserForm() {
  const router = useRouter();
  const perms = usePermissions();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string>();
  const [fields, setFields] = useState<Record<string, string[]>>({});

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setPending(true);
    try {
      const user = await createUser(
        String(form.get("email") ?? ""),
        String(form.get("full_name") ?? ""),
      );
      router.push(`/users/${encodeURIComponent(user.public_id)}`);
    } catch (err) {
      setError(usersErrorMessage(err));
      setFields(fieldErrors(err));
      setPending(false);
    }
  }

  const fieldError = (field: string) =>
    fields[field]?.length ? (
      <span className="mt-1 block text-xs text-red-600">{fields[field].join(" ")}</span>
    ) : null;

  return (
    <Gate perms={perms} code={USER_CODES.create} what="create users">
      {() => (
        <form onSubmit={handleSubmit} className={ui.card} noValidate>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            The account is created active, with no password. We email the address a link to set
            one. It holds no role until you assign one on the next screen.
          </p>
          {perms.can(INVITATION_CODES.send) ? (
            <p className="text-xs text-zinc-500">
              To give someone a role from the start, and let them choose their own name,{" "}
              <Link className="underline" href="/users/invitations">
                send an invitation
              </Link>{" "}
              instead.
            </p>
          ) : null}
          <label className="block text-sm">
            Email
            <input name="email" type="email" required autoComplete="off" className={ui.input} />
            {fieldError("email")}
          </label>
          <label className="block text-sm">
            Full name <span className="text-xs text-zinc-500">(optional)</span>
            <input name="full_name" autoComplete="off" className={ui.input} />
            {fieldError("full_name")}
          </label>
          {error ? (
            <p role="alert" className={ui.error}>
              {error}
            </p>
          ) : null}
          <button type="submit" disabled={pending} className={ui.button}>
            {pending ? "Creating…" : "Create user"}
          </button>
        </form>
      )}
    </Gate>
  );
}
