"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { type AcceptFailure, acceptFailure, acceptInvitation } from "@/lib/invitations";

export function AcceptInvitationForm({ token }: { token: string }) {
  const router = useRouter();
  const [failure, setFailure] = useState<AcceptFailure>();
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setPending(true);
    try {
      await acceptInvitation(
        token,
        String(form.get("password") ?? ""),
        String(form.get("full_name") ?? ""),
      );
      // Signed in by the API's cookies: the login page shows the signed-in state and its links.
      router.push("/login");
    } catch (error) {
      setFailure(acceptFailure(error));
      setPending(false);
    }
  }

  const card = "w-full max-w-sm rounded-xl border border-zinc-200 p-6 dark:border-zinc-800";
  const input =
    "mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 dark:border-zinc-700 dark:bg-zinc-900";

  // No token, or the API says it is unknown, used, revoked or expired: the form cannot succeed.
  if (!token || failure?.kind === "invalid-token") {
    return (
      <section className={card}>
        <p role="alert" className="text-sm text-red-600">
          {failure?.message ??
            "This invitation link is incomplete. Open the link from your email again."}
        </p>
        <Link className="mt-4 block text-sm underline" href="/login">
          Go to sign in
        </Link>
      </section>
    );
  }

  return (
    <form onSubmit={handleSubmit} className={`${card} space-y-4`} noValidate>
      <label className="block text-sm">
        Your name
        <input name="full_name" autoComplete="name" required className={input} />
      </label>
      <label className="block text-sm">
        Choose a password
        <input
          name="password"
          type="password"
          autoComplete="new-password"
          required
          className={input}
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
        {pending ? "Setting up your account…" : "Accept and sign in"}
      </button>
    </form>
  );
}
