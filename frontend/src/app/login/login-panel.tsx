"use client";

// Client component: the session is an httpOnly cookie, so who-am-I is asked from the browser.
import { type FormEvent, useEffect, useState } from "react";

import { fetchMe, type Me, signIn, signInErrorMessage, signOut } from "@/lib/auth";

type PanelState =
  | { status: "loading" }
  | { status: "signed-out"; error?: string }
  | { status: "signed-in"; me: Me };

export function LoginPanel() {
  const [state, setState] = useState<PanelState>({ status: "loading" });
  const [pending, setPending] = useState(false);

  useEffect(() => {
    let active = true;
    fetchMe()
      .then((me) => {
        if (active) setState(me ? { status: "signed-in", me } : { status: "signed-out" });
      })
      .catch(() => {
        if (active) setState({ status: "signed-out", error: signInErrorMessage(null) });
      });
    return () => {
      active = false;
    };
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setPending(true);
    try {
      await signIn(String(form.get("email") ?? ""), String(form.get("password") ?? ""));
      const me = await fetchMe();
      setState(
        me
          ? { status: "signed-in", me }
          : // Signed in, yet the next request was anonymous: the cookies did not come back.
            // Usually the frontend and API are on different sites (AUTH_BLUEPRINT § 17.1).
            { status: "signed-out", error: "Signed in, but the session cookie was not kept." },
      );
    } catch (error) {
      setState({ status: "signed-out", error: signInErrorMessage(error) });
    } finally {
      setPending(false);
    }
  }

  async function handleSignOut() {
    setPending(true);
    try {
      await signOut();
    } finally {
      setPending(false);
      setState({ status: "signed-out" });
    }
  }

  const card = "w-full max-w-sm rounded-xl border border-zinc-200 p-6 dark:border-zinc-800";

  if (state.status === "loading") {
    return <p className="text-sm text-zinc-500">Checking your session…</p>;
  }

  if (state.status === "signed-in") {
    return (
      <section className={card}>
        <p className="text-sm">
          Signed in as <strong>{state.me.email}</strong>
          {state.me.full_name ? ` (${state.me.full_name})` : ""}
        </p>
        <button
          type="button"
          onClick={handleSignOut}
          disabled={pending}
          className="mt-4 w-full rounded-md bg-zinc-900 px-3 py-2 text-sm text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
        >
          {pending ? "Signing out…" : "Sign out"}
        </button>
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
      <label className="block text-sm">
        Password
        <input
          name="password"
          type="password"
          autoComplete="current-password"
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
        {pending ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}
