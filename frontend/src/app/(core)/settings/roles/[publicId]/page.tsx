import type { Metadata } from "next";
import Link from "next/link";

import { RoleEditor } from "./role-editor";

export const metadata: Metadata = {
  title: "Role — DjangoBaseX",
  robots: { index: false, follow: false },
};

// params is a promise in Next.js 16. Only the id is read here: the role itself is authenticated
// data, fetched from the browser (NEXTJS_STANDARDS § 3).
export default async function RolePage({ params }: PageProps<"/settings/roles/[publicId]">) {
  const { publicId } = await params;

  return (
    <main className="flex min-h-screen flex-col items-center gap-6 p-8 font-sans">
      <RoleEditor publicId={publicId} />
      <Link className="text-xs text-zinc-500 underline" href="/settings/roles">
        All roles
      </Link>
    </main>
  );
}
