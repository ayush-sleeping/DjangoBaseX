import type { Metadata } from "next";
import { Suspense } from "react";

import { getServerT } from "@/core/lib/i18n/server";
import { UsersIndex } from "@/core/modules/users/Index";

// The title is the platform locale's (server rendering; FRONTEND_PLATFORM § 22).
export async function generateMetadata(): Promise<Metadata> {
  const t = await getServerT("users.index");
  return { title: t("title"), robots: { index: false, follow: false } };
}

// The list state lives in the query string, read on the client (useSearchParams): Suspense keeps the
// rest of the route prerenderable (Next 16). The data is authenticated, so it is fetched client-side.
export default function UsersPage() {
  return (
    <Suspense>
      <UsersIndex />
    </Suspense>
  );
}
