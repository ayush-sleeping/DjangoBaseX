"use client";

import { type FormEvent, useState } from "react";

import { forgotPasswordErrorMessage, requestPasswordReset } from "@/lib/password-reset";

type FormState = { status: "editing"; error?: string } | { status: "sent" };

export function ForgotPasswordForm() {
  const [state, setState] = useState<FormState>({ status: "editing" });
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setPending(true);
    try {
      await requestPasswordReset(String(form.get("email") ?? ""));
      setState({ status: "sent" });
    } catch (error) {
      setState({ status: "editing", error: forgotPasswordErrorMessage(error) });
    } finally {
      setPending(false);
    }
  }

  const card = "w-full max-w-sm rounded-xl border border-zinc-200 p-6 dark:border-zinc-800";

  if (state.status === "sent") {
    // The same words whether or not the address has an account (AUTH_BLUEPRINT § 6.6).
    return (
      <section className={card} role="status">
        <p className="text-sm">
          If an account exists for that address, we have sent it a link to reset the password.
          The link works once and expires in 30 minutes.
        </p>
      </section>
    );
  }

  return (
    <form onSubmit={handleSubmit} className={`${card} space-y-4`} noValidate>
      <label className="block text-sm">
        Email
        <input
          name="email"
          type="email"
          autoComplete="username"
          required
          className="mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 dark:border-zinc-700 dark:bg-zinc-900"
        />
      </label>
      {state.error ? (
        <p role="alert" className="text-sm text-red-600">
          {state.error}
        </p>
      ) : null}
      <button
        type="submit"
        disabled={pending}
        className="w-full rounded-md bg-zinc-900 px-3 py-2 text-sm text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
      >
        {pending ? "Sending…" : "Send reset link"}
      </button>
    </form>
  );
}
