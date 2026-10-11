import type { Metadata } from "next";
import Link from "next/link";

import { UserDetail } from "./user-detail";

export const metadata: Metadata = {
  title: "User — DjangoBaseX",
  robots: { index: false, follow: false },
};

// params is a promise in Next.js 16. Only the id is read here: the user is authenticated data,
// fetched from the browser (NEXTJS_STANDARDS § 3).
export default async function UserPage({ params }: PageProps<"/users/[publicId]">) {
  const { publicId } = await params;

  return (
    <main className="flex min-h-screen flex-col items-center gap-6 p-8 font-sans">
      <UserDetail publicId={publicId} />
      <Link className="text-xs text-zinc-500 underline" href="/users">
        All users
      </Link>
    </main>
  );
}
