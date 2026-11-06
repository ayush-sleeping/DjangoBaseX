import type { Metadata } from "next";

import { UserCreatePage } from "@/core/modules/users/Form";

export const metadata: Metadata = { title: "New user", robots: { index: false, follow: false } };

// The deep-linkable twin of the index's "New user" modal (FRONTEND_PLATFORM § 11).
export default function NewUserPage() {
  return <UserCreatePage />;
}
