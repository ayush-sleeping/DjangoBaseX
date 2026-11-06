import type { Metadata } from "next";
import { Suspense } from "react";

import { UsersIndex } from "@/core/modules/users/Index";

export const metadata: Metadata = { title: "Users", robots: { index: false, follow: false } };

// The list state lives in the query string, read on the client (useSearchParams): Suspense keeps the
// rest of the route prerenderable (Next 16). The data is authenticated, so it is fetched client-side.
export default function UsersPage() {
  return (
    <Suspense>
      <UsersIndex />
    </Suspense>
  );
}
