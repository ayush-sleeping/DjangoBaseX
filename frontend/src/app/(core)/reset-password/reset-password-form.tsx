"use client";

import Link from "next/link";
import { type FormEvent, useState } from "react";

import { type ResetFailure, resetFailure, resetPassword } from "@/core/lib/password-reset";

type FormState = { status: "editing"; failure?: ResetFailure } | { status: "done" };

export function ResetPasswordForm({ token }: { token: string }) {
  const [state, setState] = useState<FormState>({ status: "editing" });
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setPending(true);
    try {
      await resetPassword(token, String(form.get("password") ?? ""));
      setState({ status: "done" });
    } catch (error) {
      setState({ status: "editing", failure: resetFailure(error) });
    } finally {
      setPending(false);
    }
  }

  const card = "w-full max-w-sm rounded-xl border border-zinc-200 p-6 dark:border-zinc-800";
  const link = "text-sm underline";

  if (state.status === "done") {
    return (
      <section className={card} role="status">
        <p className="text-sm">
          Your password has been changed, and every session on every device has been signed out.
        </p>
        <Link className={`${link} mt-4 block`} href="/login">
          Sign in with your new password
        </Link>
      </section>
    );
  }

  // No token, or the API has said it is unknown, used or expired: the form cannot succeed.
  const failure = state.failure;
  if (!token || failure?.kind === "invalid-token") {
    return (
      <section className={card}>
        <p role="alert" className="text-sm text-red-600">
          {failure?.message ?? "This reset link is incomplete. Request a new one."}
        </p>
        <Link className={`${link} mt-4 block`} href="/forgot-password">
          Request a new reset link
        </Link>
      </section>
    );
  }

  return (
    <form onSubmit={handleSubmit} className={`${card} space-y-4`} noValidate>
      <label className="block text-sm">
        New password
        <input
          name="password"
          type="password"
          autoComplete="new-password"
          required
          className="mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 dark:border-zinc-700 dark:bg-zinc-900"
        />
      </label>
      {failure ? (
        <div role="alert" className="text-sm text-red-600">
          <p>{failure.message}</p>
          {failure.kind === "invalid-password" && failure.details.length > 0 ? (
            <ul className="mt-1 list-disc pl-5">
              {failure.details.map((detail) => (
                <li key={detail}>{detail}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
      <button
        type="submit"
        disabled={pending}
        className="w-full rounded-md bg-zinc-900 px-3 py-2 text-sm text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
      >
        {pending ? "Saving…" : "Set new password"}
      </button>
    </form>
  );
}
