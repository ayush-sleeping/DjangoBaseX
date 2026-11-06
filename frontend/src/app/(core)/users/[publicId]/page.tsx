import type { Metadata } from "next";

import { UserShow } from "@/core/modules/users/Show";

export const metadata: Metadata = { title: "User", robots: { index: false, follow: false } };

// params is a promise in Next.js 16. Only the id is read here: the user is authenticated data,
// fetched from the browser (NEXTJS_STANDARDS § 3).
export default async function UserPage({ params }: PageProps<"/users/[publicId]">) {
  const { publicId } = await params;
  return <UserShow publicId={publicId} />;
}
