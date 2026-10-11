import type { Metadata } from "next";
import Link from "next/link";

import { tokenFromSearchParams } from "@/core/lib/password-reset";

import { ResetPasswordForm } from "./reset-password-form";

export const metadata: Metadata = {
  title: "Reset password — DjangoBaseX",
  // The token is in this page's URL: never send it to another site in a Referer header.
  referrer: "no-referrer",
  robots: { index: false, follow: false },
};

// searchParams is a promise in Next.js 16, and reading it makes the page render per request.
export default async function ResetPasswordPage({ searchParams }: PageProps<"/reset-password">) {
  const token = tokenFromSearchParams((await searchParams).token);

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 p-8 font-sans">
      <h1 className="text-2xl font-bold tracking-tight">Reset password</h1>
      <ResetPasswordForm token={token} />
      <Link className="text-xs text-zinc-500 underline" href="/login">
        Back to sign in
      </Link>
    </main>
  );
}
