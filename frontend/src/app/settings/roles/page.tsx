import type { Metadata } from "next";
import Link from "next/link";

import { RolesPanel } from "./roles-panel";

export const metadata: Metadata = {
  title: "Roles — DjangoBaseX",
  robots: { index: false, follow: false },
};

// A server shell only: roles are authenticated data, fetched from the browser (NEXTJS_STANDARDS § 3).
export default function RolesPage() {
  return (
    <main className="flex min-h-screen flex-col items-center gap-6 p-8 font-sans">
      <h1 className="text-2xl font-bold tracking-tight">Roles</h1>
      <RolesPanel />
      <Link className="text-xs text-zinc-500 underline" href="/login">
        Back to your account
      </Link>
    </main>
  );
}
