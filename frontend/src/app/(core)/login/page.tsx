import type { Metadata } from "next";
import Link from "next/link";

import { LoginPanel } from "./login-panel";

export const metadata: Metadata = {
  title: "Sign in — DjangoBaseX",
};

export default function LoginPage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 p-8 font-sans">
      <h1 className="text-2xl font-bold tracking-tight">Sign in</h1>
      <LoginPanel />
      <Link className="text-xs text-zinc-500 underline" href="/">
        Back to the status page
      </Link>
    </main>
  );
}
