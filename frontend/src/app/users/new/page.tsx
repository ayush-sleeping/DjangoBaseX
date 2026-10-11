import type { Metadata } from "next";
import Link from "next/link";

import { NewUserForm } from "./new-user-form";

export const metadata: Metadata = {
  title: "New user — DjangoBaseX",
  robots: { index: false, follow: false },
};

export default function NewUserPage() {
  return (
    <main className="flex min-h-screen flex-col items-center gap-6 p-8 font-sans">
      <h1 className="text-2xl font-bold tracking-tight">New user</h1>
      <NewUserForm />
      <Link className="text-xs text-zinc-500 underline" href="/users">
        All users
      </Link>
    </main>
  );
}
