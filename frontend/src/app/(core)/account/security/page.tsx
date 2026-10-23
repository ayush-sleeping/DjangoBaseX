import type { Metadata } from "next";
import Link from "next/link";

import { SecurityPanel } from "./security-panel";

export const metadata: Metadata = {
  title: "Account security",
  robots: { index: false, follow: false },
};

// A server shell only: who is signed in is asked from the browser (NEXTJS_STANDARDS.md § 3).
export default function SecurityPage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 p-8 font-sans">
      <h1 className="text-2xl font-bold tracking-tight">Account security</h1>
      <SecurityPanel />
      <Link className="text-xs text-zinc-500 underline" href="/login">
        Back to your account
      </Link>
    </main>
  );
}
