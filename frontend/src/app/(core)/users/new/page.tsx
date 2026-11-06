import type { Metadata } from "next";

import { getServerT } from "@/core/lib/i18n/server";
import { UserCreatePage } from "@/core/modules/users/Form";

// The title is the platform locale's (server rendering; FRONTEND_PLATFORM § 22).
export async function generateMetadata(): Promise<Metadata> {
  const t = await getServerT("users.new");
  return { title: t("title"), robots: { index: false, follow: false } };
}

// The deep-linkable twin of the index's "New user" modal (FRONTEND_PLATFORM § 11).
export default function NewUserPage() {
  return <UserCreatePage />;
}
