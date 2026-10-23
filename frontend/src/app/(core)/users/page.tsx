import type { Metadata } from "next";
import Link from "next/link";

import { pageFromSearchParams } from "@/core/lib/users";

import { UsersPanel } from "./users-panel";

export const metadata: Metadata = {
  title: "Users",
  robots: { index: false, follow: false },
};

// The query string seeds the list (shareable links, Back); the data itself is fetched from the
// browser, because it is authenticated (NEXTJS_STANDARDS § 3). searchParams is async in Next 16.
export default async function UsersPage({ searchParams }: PageProps<"/users">) {
  const query = await searchParams;
  const search = Array.isArray(query.search) ? query.search[0] : query.search;

  return (
    <main className="flex min-h-screen flex-col items-center gap-6 p-8 font-sans">
      <h1 className="text-2xl font-bold tracking-tight">Users</h1>
      <UsersPanel initialPage={pageFromSearchParams(query.page)} initialSearch={search ?? ""} />
      <Link className="text-xs text-zinc-500 underline" href="/login">
        Back to your account
      </Link>
    </main>
  );
}
