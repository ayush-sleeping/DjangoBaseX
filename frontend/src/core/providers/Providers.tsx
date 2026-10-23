"use client";

/**
 * The root provider tree (FRONTEND_PLATFORM.md § 1), outermost first. As built after 8.1 it
 * holds the QueryClientProvider; the identity, theme, session and permission providers join as
 * their tasks land (8.2+), in the order § 1 fixes. The client is created once per browser
 * session in useState, never at module scope.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { makeQueryClient } from "@/core/lib/query/client";

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(makeQueryClient);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
