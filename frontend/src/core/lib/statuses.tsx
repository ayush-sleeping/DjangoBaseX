"use client";

/**
 * Status metadata (FRONTEND_PLATFORM § 13, BUILD_ORDER 8.4a): a status key → its label and tone,
 * decided once by the backend app that owns it.
 *
 * Two sources, one answer: bootstrap's `statuses` (every installed app's, linked plugins included)
 * when the shell has it, else the generated core table (src/generated/statuses.ts) — so a chip has
 * its tone before bootstrap arrives, in a signed-out page, and in a test with no provider.
 */
import { createContext, type ReactNode, useContext } from "react";

import { type StatusMeta, STATUSES } from "@/generated/statuses";

import { useBootstrap } from "./bootstrap";

const Ctx = createContext<Readonly<Record<string, StatusMeta>> | null>(null);

/** Mounted once in the root providers, under the QueryClientProvider. */
export function StatusProvider({ children }: { children: ReactNode }) {
  const boot = useBootstrap();
  return <Ctx.Provider value={boot.data?.statuses ?? null}>{children}</Ctx.Provider>;
}

/** The metadata for a status key, or undefined for a key no app registered. */
export function useStatus(key: string | null | undefined): StatusMeta | undefined {
  const live = useContext(Ctx);
  if (!key) return undefined;
  if (live && Object.hasOwn(live, key)) return live[key];
  return Object.hasOwn(STATUSES, key) ? STATUSES[key as keyof typeof STATUSES] : undefined;
}
