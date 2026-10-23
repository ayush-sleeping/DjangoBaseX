/**
 * "Couldn't refresh — showing the last loaded copy." A failed background refetch keeps the data
 * and announces itself ONCE per distinct error (kind + code + status), through a module-level
 * store that outlives the page. The toast host (FRONTEND_PLATFORM § 13) subscribes; until it
 * exists, subscribers are tests.
 */
import { isApiError } from "@/core/lib/api/errors";

export type RefreshFailed = { key: string; message: string };

type Listener = (event: RefreshFailed) => void;
const listeners = new Set<Listener>();
const announced = new Set<string>();

export function dedupeKey(error: unknown): string {
  if (isApiError(error)) return `${error.kind}:${error.code}:${error.status}`;
  return `unknown:${error instanceof Error ? error.name : typeof error}`;
}

export function subscribeRefreshFailed(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function notifyRefreshFailed(error: unknown): void {
  const key = dedupeKey(error);
  if (announced.has(key)) return;
  announced.add(key);
  const event = { key, message: "Couldn't refresh — showing the last loaded copy." };
  for (const listener of listeners) listener(event);
}

/** Tests only: forget what was announced. */
export function resetRefreshFailed(): void {
  announced.clear();
}
