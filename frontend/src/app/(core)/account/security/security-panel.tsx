"use client";

// Client component: the session is an httpOnly cookie, so who-am-I is asked from the browser.
import Link from "next/link";
import { type FormEvent, useEffect, useState } from "react";

import { isReauthRequired } from "@/core/lib/api";
import { fetchMe, type Me } from "@/core/lib/auth";
import {
  confirmMfaSetup,
  confirmPasswordAndDisableMfa,
  disableMfa,
  formatSecret,
  type MfaSetup,
  mfaErrorMessage,
  recoveryCodesText,
  startMfaSetup,
} from "@/core/lib/mfa";

type View =
  | { status: "loading" }
  | { status: "signed-out" }
  | { status: "unavailable" }
  | { status: "overview"; me: Me; notice?: string; error?: string }
  | { status: "setup"; me: Me; setup: MfaSetup; error?: string }
  // Shown once. Leaving this view drops the codes: they are never stored client-side.
  | { status: "recovery"; me: Me; codes: string[]; copy?: "copied" | "failed" }
  | { status: "disable"; me: Me; needsPassword: boolean; error?: string };

export function SecurityPanel() {
  const [view, setView] = useState<View>({ status: "loading" });
  const [pending, setPending] = useState(false);

  useEffect(() => {
    let active = true;
    fetchMe()
      .then((me) => {
        if (active) setView(me ? { status: "overview", me } : { status: "signed-out" });
      })
      .catch(() => {
        if (active) setView({ status: "unavailable" });
      });
    return () => {
      active = false;
    };
  }, []);

  /** Re-reads /me so the status shown is the server's, not a guess. */
  async function showOverview(notice?: string) {
    try {
      const me = await fetchMe();
      setView(me ? { status: "overview", me, notice } : { status: "signed-out" });
    } catch {
      setView({ status: "unavailable" });
    }
  }

  async function run(action: () => Promise<void>) {
    setPending(true);
    try {
      await action();
    } finally {
      setPending(false);
    }
  }

  function handleStartSetup(me: Me) {
    return run(async () => {
      try {
        setView({ status: "setup", me, setup: await startMfaSetup() });
      } catch (error) {
        setView({ status: "overview", me, error: mfaErrorMessage(error) });
      }
    });
  }

  function handleConfirm(event: FormEvent<HTMLFormElement>, me: Me, setup: MfaSetup) {
    event.preventDefault();
    const code = String(new FormData(event.currentTarget).get("code") ?? "");
    return run(async () => {
      try {
        setView({ status: "recovery", me, codes: await confirmMfaSetup(code) });
      } catch (error) {
        setView({ status: "setup", me, setup, error: mfaErrorMessage(error) });
      }
    });
  }

  async function handleCopy(me: Me, codes: string[]) {
    try {
      await navigator.clipboard.writeText(recoveryCodesText(codes));
      setView({ status: "recovery", me, codes, copy: "copied" });
    } catch {
      // No clipboard outside a secure context (plain http on a non-localhost host).
      setView({ status: "recovery", me, codes, copy: "failed" });
    }
  }

  function handleDisable(me: Me) {
    return run(async () => {
      try {
        await disableMfa();
        await showOverview("Two-factor authentication is off.");
      } catch (error) {
        setView(
          isReauthRequired(error)
            ? { status: "disable", me, needsPassword: true }
            : { status: "disable", me, needsPassword: false, error: mfaErrorMessage(error) },
        );
      }
    });
  }

  function handleDisableWithPassword(event: FormEvent<HTMLFormElement>, me: Me) {
    event.preventDefault();
    const password = String(new FormData(event.currentTarget).get("password") ?? "");
    return run(async () => {
      try {
        await confirmPasswordAndDisableMfa(password);
        await showOverview("Two-factor authentication is off.");
      } catch (error) {
        setView({ status: "disable", me, needsPassword: true, error: mfaErrorMessage(error) });
      }
    });
  }

  const card =
    "w-full max-w-md space-y-4 rounded-xl border border-border p-6";
  const input =
    "mt-1 w-full rounded-md border border-input px-3 py-2";
  const button =
    "w-full rounded-md bg-primary px-3 py-2 text-sm text-primary-foreground disabled:opacity-50";
  const quiet = "block w-full text-center text-xs text-muted-foreground underline";

  switch (view.status) {
    case "loading":
      return <p className="text-sm text-muted-foreground">Checking your session…</p>;

    case "signed-out":
      return (
        <section className={card}>
          <p className="text-sm">Sign in to manage your account security.</p>
          <Link className="block text-sm underline" href="/login">
            Sign in
          </Link>
        </section>
      );

    case "unavailable":
      return (
        <p role="alert" className="text-sm text-destructive">
          Could not reach the server. Reload the page to try again.
        </p>
      );

    case "overview": {
      const { me } = view;
      return (
        <section className={card}>
          <h2 className="text-sm font-semibold">Two-factor authentication</h2>
          {view.notice ? (
            <p role="status" className="text-sm text-ok-text">
              {view.notice}
            </p>
          ) : null}
          {me.mfa_enabled ? (
            <p className="text-sm">
              <strong>On.</strong> Signing in asks for a code from your authenticator app.
            </p>
          ) : (
            <p className="text-sm">
              <strong>Off.</strong> Add a second step to sign-in with an authenticator app.
            </p>
          )}
          {me.mfa_enforced && !me.mfa_enabled ? (
            <p role="alert" className="text-sm text-warn-text">
              Your role requires two-factor authentication. Until it is set up, the rest of the
              application is unavailable to you.
            </p>
          ) : null}
          {view.error ? (
            <p role="alert" className="text-sm text-destructive">
              {view.error}
            </p>
          ) : null}
          {me.mfa_enabled ? (
            <button
              type="button"
              onClick={() => setView({ status: "disable", me, needsPassword: false })}
              className={button}
            >
              Turn off two-factor
            </button>
          ) : (
            <button
              type="button"
              onClick={() => handleStartSetup(me)}
              disabled={pending}
              className={button}
            >
              {pending ? "Preparing…" : "Set up two-factor"}
            </button>
          )}
        </section>
      );
    }

    case "setup": {
      const { me, setup } = view;
      return (
        <form onSubmit={(event) => handleConfirm(event, me, setup)} className={card} noValidate>
          <h2 className="text-sm font-semibold">Set up two-factor</h2>
          <ol className="list-decimal space-y-3 pl-5 text-sm">
            <li>
              In your authenticator app, add an account and enter this key:
              <code className="mt-1 block select-all rounded bg-muted px-2 py-1 font-mono tracking-wider">
                {formatSecret(setup.secret)}
              </code>
              <span className="mt-1 block text-xs text-muted-foreground">
                On this device, you can{" "}
                <a className="underline" href={setup.otpauth_uri}>
                  open it in your authenticator app
                </a>{" "}
                instead, or copy the setup link:
              </span>
              <code className="mt-1 block select-all break-all rounded bg-muted px-2 py-1 font-mono text-xs">
                {setup.otpauth_uri}
              </code>
            </li>
            <li>
              <label className="block">
                Enter the 6-digit code it shows
                <input
                  name="code"
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  required
                  className={input}
                />
              </label>
            </li>
          </ol>
          {view.error ? (
            <p role="alert" className="text-sm text-destructive">
              {view.error}
            </p>
          ) : null}
          <button type="submit" disabled={pending} className={button}>
            {pending ? "Checking…" : "Turn on two-factor"}
          </button>
          <button type="button" onClick={() => showOverview()} className={quiet}>
            Cancel
          </button>
        </form>
      );
    }

    case "recovery": {
      const { me, codes } = view;
      return (
        <section className={card}>
          <h2 className="text-sm font-semibold">Two-factor is on. Save your recovery codes now.</h2>
          <p role="alert" className="text-sm text-warn-text">
            Each code signs you in once if you lose your authenticator. They are shown only this
            once: store them somewhere safe, such as a password manager, before you leave.
          </p>
          <ul className="grid select-all grid-cols-2 gap-1 rounded bg-muted p-3 font-mono text-sm">
            {codes.map((code) => (
              <li key={code}>{code}</li>
            ))}
          </ul>
          <button type="button" onClick={() => handleCopy(me, codes)} className={button}>
            Copy all codes
          </button>
          {view.copy === "copied" ? (
            <p role="status" className="text-sm text-ok-text">
              Copied.
            </p>
          ) : view.copy === "failed" ? (
            <p role="alert" className="text-sm text-destructive">
              Could not copy. Select the codes above and copy them by hand.
            </p>
          ) : null}
          <button
            type="button"
            onClick={() => showOverview("Two-factor authentication is on.")}
            className={quiet}
          >
            I have saved my recovery codes
          </button>
        </section>
      );
    }

    case "disable": {
      const { me } = view;
      if (view.needsPassword) {
        return (
          <form
            onSubmit={(event) => handleDisableWithPassword(event, me)}
            className={card}
            noValidate
          >
            <h2 className="text-sm font-semibold">Confirm your password</h2>
            <p className="text-sm">Turning off two-factor needs your password again.</p>
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
            {view.error ? (
              <p role="alert" className="text-sm text-destructive">
                {view.error}
              </p>
            ) : null}
            <button type="submit" disabled={pending} className={button}>
              {pending ? "Turning off…" : "Confirm and turn off"}
            </button>
            <button type="button" onClick={() => showOverview()} className={quiet}>
              Cancel
            </button>
          </form>
        );
      }
      return (
        <section className={card}>
          <h2 className="text-sm font-semibold">Turn off two-factor?</h2>
          <p className="text-sm">Anyone with your password will be able to sign in as you.</p>
          {view.error ? (
            <p role="alert" className="text-sm text-destructive">
              {view.error}
            </p>
          ) : null}
          <button
            type="button"
            onClick={() => handleDisable(me)}
            disabled={pending}
            className={button}
          >
            {pending ? "Turning off…" : "Turn off two-factor"}
          </button>
          <button type="button" onClick={() => showOverview()} className={quiet}>
            Cancel
          </button>
        </section>
      );
    }
  }
}
