import type { Metadata } from "next";
import Link from "next/link";

import { tokenFromSearchParams } from "@/core/lib/password-reset";

import { AcceptInvitationForm } from "./accept-invitation-form";

export const metadata: Metadata = {
  title: "Accept invitation",
  // The token is in this page's URL: never send it to another site in a Referer header
  // (NEXTJS_STANDARDS § 3, the token-page rule).
  referrer: "no-referrer",
  robots: { index: false, follow: false },
};

// Public: the token in the emailed link is the credential. searchParams is async in Next 16.
export default async function AcceptInvitationPage({
  searchParams,
}: PageProps<"/accept-invitation">) {
  const token = tokenFromSearchParams((await searchParams).token);

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 p-8 font-sans">
      <h1 className="text-2xl font-bold tracking-tight">Accept your invitation</h1>
      <AcceptInvitationForm token={token} />
      <Link className="text-xs text-zinc-500 underline" href="/login">
        Already have an account? Sign in
      </Link>
    </main>
  );
}
