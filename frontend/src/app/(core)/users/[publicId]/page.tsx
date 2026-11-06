import type { Metadata } from "next";

import { getServerT } from "@/core/lib/i18n/server";
import { UserShow } from "@/core/modules/users/Show";

// The title is the platform locale's (server rendering; FRONTEND_PLATFORM § 22).
export async function generateMetadata(): Promise<Metadata> {
  const t = await getServerT("users.show");
  return { title: t("title"), robots: { index: false, follow: false } };
}

// params is a promise in Next.js 16. Only the id is read here: the user is authenticated data,
// fetched from the browser (NEXTJS_STANDARDS § 3).
export default async function UserPage({ params }: PageProps<"/users/[publicId]">) {
  const { publicId } = await params;
  return <UserShow publicId={publicId} />;
}
