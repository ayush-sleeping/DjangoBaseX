"use client";

// Client component: the session is an httpOnly cookie, so who-am-I is asked from the browser.
import Link from "next/link";
import { type FormEvent, useEffect, useState } from "react";

import {
  completeMfaSignIn,
  fetchMe,
  type Me,
  mfaStepFailure,
  signIn,
  signInErrorMessage,
  signOut,
} from "@/core/lib/auth";
import { MFA_ENROLMENT_PATH } from "@/core/lib/mfa";
import { hardNavigate } from "@/core/lib/session/navigate";
import { safeNext } from "@/core/lib/session/safe-next";

type PanelState =
  | { status: "loading" }
  | { status: "signed-out"; error?: string }
  | { status: "mfa"; mfaToken: string; error?: string }
  | { status: "signed-in"; me: Me };

/** `next`: where the proxy was sending the user before it asked them to sign in (unchecked). */
export function LoginPanel({ next }: { next?: string }) {
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

  async function showSignedIn() {
    const me = await fetchMe();
    if (!me) {
      // Signed in, yet the next request was anonymous: the cookies did not come back.
      // Usually the frontend and API are on different sites (AUTH_BLUEPRINT § 17.1).
      setState({ status: "signed-out", error: "Signed in, but the session cookie was not kept." });
      return;
    }
    // An identity change: a HARD navigation, so no cache from before sign-in (the provider's
    // signed-out bootstrap among them) survives into the session (FRONTEND_PLATFORM § 8.4).
    hardNavigate(safeNext(next));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setPending(true);
    try {
      const result = await signIn(
        String(form.get("email") ?? ""),
        String(form.get("password") ?? ""),
      );
      if (result.status === "mfa-required") {
        setState({ status: "mfa", mfaToken: result.mfaToken });
      } else {
        await showSignedIn();
      }
    } catch (error) {
      setState({ status: "signed-out", error: signInErrorMessage(error) });
    } finally {
      setPending(false);
    }
  }

  async function handleCode(event: FormEvent<HTMLFormElement>, mfaToken: string) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setPending(true);
    try {
      await completeMfaSignIn(mfaToken, String(form.get("code") ?? ""));
      await showSignedIn();
    } catch (error) {
      const failure = mfaStepFailure(error);
      setState(
        failure.restart
          ? { status: "signed-out", error: failure.message }
          : { status: "mfa", mfaToken, error: failure.message },
      );
    } finally {
      setPending(false);
    }
  }

  async function handleSignOut() {
    setPending(true);
    try {
      await signOut();
    } finally {
      // Hard navigation: the signed-in user's cached bootstrap and data must not outlive them.
      hardNavigate("/login");
    }
  }

  const card = "w-full max-w-sm rounded-xl border border-border p-6";
  const input =
    "mt-1 w-full rounded-md border border-input px-3 py-2";
  const button =
    "w-full rounded-md bg-primary px-3 py-2 text-sm text-primary-foreground disabled:opacity-50";

  if (state.status === "loading") {
    return <p className="text-sm text-muted-foreground">Checking your session…</p>;
  }

  if (state.status === "signed-in") {
    const { me } = state;
    return (
      <section className={card}>
        <p className="text-sm">
          Signed in as <strong>{me.email}</strong>
          {me.full_name ? ` (${me.full_name})` : ""}
        </p>
        {me.mfa_enforced && !me.mfa_enabled ? (
          <p role="alert" className="mt-3 text-sm text-warn-text">
            Your role requires two-factor authentication. Set it up before you continue.
          </p>
        ) : null}
        <Link className="mt-3 block text-sm underline" href={safeNext(next)}>
          Continue
        </Link>
        <Link className="mt-1 block text-sm underline" href={MFA_ENROLMENT_PATH}>
          Account security
        </Link>
        <button
          type="button"
          onClick={handleSignOut}
          disabled={pending}
          className={`mt-4 ${button}`}
        >
          {pending ? "Signing out…" : "Sign out"}
        </button>
      </section>
    );
  }

  if (state.status === "mfa") {
    const { mfaToken } = state;
    return (
      <form
        onSubmit={(event) => handleCode(event, mfaToken)}
        className={`${card} space-y-4`}
        noValidate
      >
        <p className="text-sm">
          Enter the 6-digit code from your authenticator app, or one of your recovery codes.
        </p>
        <label className="block text-sm">
          Code
          <input
            name="code"
            type="text"
            autoComplete="one-time-code"
            autoCapitalize="characters"
            spellCheck={false}
            required
            autoFocus
            className={input}
          />
        </label>
        {state.error ? (
          <p role="alert" className="text-sm text-destructive">
            {state.error}
          </p>
        ) : null}
        <button type="submit" disabled={pending} className={button}>
          {pending ? "Checking…" : "Verify"}
        </button>
        <button
          type="button"
          onClick={() => setState({ status: "signed-out" })}
          className="block w-full text-center text-xs text-muted-foreground underline"
        >
          Start again
        </button>
      </form>
    );
  }

  return (
    <form onSubmit={handleSubmit} className={`${card} space-y-4`} noValidate>
      <label className="block text-sm">
        Email
        <input name="email" type="email" autoComplete="username" required className={input} />
      </label>
      <label className="block text-sm">
        Password
        <input
          name="password"
          type="password"
          autoComplete="current-password"
          required
          className={input}
        />
      </label>
      {state.error ? (
        <p role="alert" className="text-sm text-destructive">
          {state.error}
        </p>
      ) : null}
      <button type="submit" disabled={pending} className={button}>
        {pending ? "Signing in…" : "Sign in"}
      </button>
      <Link className="block text-center text-xs text-muted-foreground underline" href="/forgot-password">
        Forgot password?
      </Link>
    </form>
  );
}
