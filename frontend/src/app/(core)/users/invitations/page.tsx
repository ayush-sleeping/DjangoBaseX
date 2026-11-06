import type { Metadata } from "next";
import { Suspense } from "react";

import { InvitationsIndex } from "@/core/modules/users/InvitationsIndex";

export const metadata: Metadata = { title: "Invitations", robots: { index: false, follow: false } };

// A static segment, so /users/invitations wins over /users/[publicId].
export default function InvitationsPage() {
  return (
    <Suspense>
      <InvitationsIndex />
    </Suspense>
  );
}
