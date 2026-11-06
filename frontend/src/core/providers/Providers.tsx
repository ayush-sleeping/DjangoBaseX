"use client";

/**
 * The root provider tree (FRONTEND_PLATFORM.md § 1), outermost first: the QueryClientProvider,
 * then the PermissionProvider (8.2, fed by bootstrap), and the one ConfirmHost and Toaster (8.3a)
 * that confirm() and toast() talk to. The identity and session providers join as their tasks land,
 * in the order § 1 fixes. The client is created once per browser session in useState, never at
 * module scope.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { ConfirmHost } from "@/core/components/confirm";
import { Toaster } from "@/core/components/toast";
import { PermissionProvider } from "@/core/lib/permissions";
import { makeQueryClient } from "@/core/lib/query/client";
import { StatusProvider } from "@/core/lib/statuses";

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(makeQueryClient);
  return (
    <QueryClientProvider client={client}>
      <PermissionProvider>
        <StatusProvider>{children}</StatusProvider>
      </PermissionProvider>
      <ConfirmHost />
      <Toaster />
    </QueryClientProvider>
  );
}
