"use client";

/**
 * The root provider tree (FRONTEND_PLATFORM.md § 1), outermost first: the QueryClientProvider,
 * then the PermissionProvider (8.2, fed by bootstrap). The identity, theme and session providers
 * join as their tasks land, in the order § 1 fixes. The client is created once per browser session
 * in useState, never at module scope.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { PermissionProvider } from "@/core/lib/permissions";
import { makeQueryClient } from "@/core/lib/query/client";

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(makeQueryClient);
  return (
    <QueryClientProvider client={client}>
      <PermissionProvider>{children}</PermissionProvider>
    </QueryClientProvider>
  );
}
