import type { SortState } from "./types";

export function parseOrdering(ordering: string | null | undefined): SortState {
  if (!ordering) return null;
  const first = ordering.split(",")[0].trim();
  if (!first) return null;
  return first.startsWith("-") ? { key: first.slice(1), desc: true } : { key: first, desc: false };
}

/** Clicking a header cycles ascending → descending → the API's default. */
export function nextOrdering(current: SortState, key: string): string | null {
  if (!current || current.key !== key) return key;
  return current.desc ? null : `-${key}`;
}
