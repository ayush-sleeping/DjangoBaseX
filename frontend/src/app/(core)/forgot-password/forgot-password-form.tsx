"use client";

import { type FormEvent, useState } from "react";

import { forgotPasswordErrorMessage, requestPasswordReset } from "@/core/lib/password-reset";

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

  const card = "w-full max-w-sm rounded-xl border border-border p-6";

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
          className="mt-1 w-full rounded-md border border-input px-3 py-2"
        />
      </label>
      {state.error ? (
        <p role="alert" className="text-sm text-destructive">
          {state.error}
        </p>
      ) : null}
      <button
        type="submit"
        disabled={pending}
        className="w-full rounded-md bg-primary px-3 py-2 text-sm text-primary-foreground disabled:opacity-50"
      >
        {pending ? "Sending…" : "Send reset link"}
      </button>
    </form>
  );
}
