import type { Metadata } from "next";
import { Suspense } from "react";

import { getServerT } from "@/core/lib/i18n/server";
import { InvitationsIndex } from "@/core/modules/users/InvitationsIndex";

// The title is the platform locale's (server rendering; FRONTEND_PLATFORM § 22).
export async function generateMetadata(): Promise<Metadata> {
  const t = await getServerT("users.invitations");
  return { title: t("title"), robots: { index: false, follow: false } };
}

// A static segment, so /users/invitations wins over /users/[publicId].
export default function InvitationsPage() {
  return (
    <Suspense>
      <InvitationsIndex />
    </Suspense>
  );
}
