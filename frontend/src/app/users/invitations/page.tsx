import type { Metadata } from "next";
import Link from "next/link";

import { InvitationsPanel } from "./invitations-panel";

export const metadata: Metadata = {
  title: "Invitations — DjangoBaseX",
  robots: { index: false, follow: false },
};

// A static segment, so /users/invitations wins over /users/[publicId].
export default function InvitationsPage() {
  return (
    <main className="flex min-h-screen flex-col items-center gap-6 p-8 font-sans">
      <h1 className="text-2xl font-bold tracking-tight">Invitations</h1>
      <InvitationsPanel />
      <Link className="text-xs text-zinc-500 underline" href="/users">
        All users
      </Link>
    </main>
  );
}
