import type { Metadata } from "next";
import Link from "next/link";

import { getIdentity } from "@/core/lib/identity";

import { LoginPanel } from "./login-panel";

export const metadata: Metadata = {
  title: "Sign in",
};

export default async function LoginPage() {
  const { product_name, tagline } = await getIdentity();
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 p-8 font-sans">
      <div className="text-center">
        <p className="text-sm font-semibold text-zinc-500">{product_name}</p>
        <h1 className="text-2xl font-bold tracking-tight">Sign in</h1>
        {tagline && <p className="mt-1 text-xs text-zinc-500">{tagline}</p>}
      </div>
      <LoginPanel />
      <Link className="text-xs text-zinc-500 underline" href="/">
        Back to the status page
      </Link>
    </main>
  );
}
