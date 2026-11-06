"use client";

/**
 * URL-backed list state (FRONTEND_PLATFORM § 6, BUILD_ORDER 8.3b): page, search, ordering and
 * filters live in the query string, so a list is shareable, Back works, and a refresh lands on the
 * same rows. Any change except paging resets to page 1 — page 7 of a different search is a stale
 * page, not a place.
 *
 * A component using this reads useSearchParams(): render it under a <Suspense> boundary (Next 16
 * client-renders up to the nearest one on a prerendered route).
 */
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo } from "react";

export type ListState = {
  page: number;
  search: string;
  /** "field" or "-field", exactly what the API's `ordering` takes; null for the API's default. */
  ordering: string | null;
  filters: Record<string, string>;
};

const RESERVED = new Set(["page", "search", "ordering"]);
const ORDERING = /^-?[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$/i;

export function parseListState(params: URLSearchParams, filterKeys: readonly string[] = []): ListState {
  const page = Number.parseInt(params.get("page") ?? "", 10);
  const ordering = params.get("ordering");
  const filters: Record<string, string> = {};
  for (const key of filterKeys) {
    if (RESERVED.has(key)) throw new Error(`list-state: "${key}" is reserved and cannot be a filter`);
    const value = params.get(key);
    if (value) filters[key] = value;
  }
  return {
    page: Number.isFinite(page) && page > 0 ? page : 1,
    search: (params.get("search") ?? "").trim(),
    // An ordering that is not a plain field name is dropped, never forwarded to the API.
    ordering: ordering && ORDERING.test(ordering) ? ordering : null,
    filters,
  };
}

/** The query string for a state; defaults are omitted, so the canonical URL is the shortest. */
export function listStateToParams(state: ListState): URLSearchParams {
  const params = new URLSearchParams();
  if (state.page > 1) params.set("page", String(state.page));
  if (state.search) params.set("search", state.search);
  if (state.ordering) params.set("ordering", state.ordering);
  for (const [key, value] of Object.entries(state.filters).sort(([a], [b]) => a.localeCompare(b))) {
    if (value) params.set(key, value);
  }
  return params;
}

export type ListStateApi = ListState & {
  setPage: (page: number) => void;
  setSearch: (search: string) => void;
  setOrdering: (ordering: string | null) => void;
  setFilter: (key: string, value: string | null) => void;
  clearFilters: () => void;
  /** Search or a filter is narrowing the list: an empty result is "filtered", not "none yet". */
  isFiltered: boolean;
};

export function useListState({ filterKeys = [] }: { filterKeys?: readonly string[] } = {}): ListStateApi {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const keys = filterKeys.join(",");
  const state = useMemo(() => parseListState(new URLSearchParams(params.toString()), keys ? keys.split(",") : []), [params, keys]);

  const go = useCallback(
    (next: ListState) => {
      const qs = listStateToParams(next).toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [router, pathname],
  );

  return {
    ...state,
    isFiltered: Boolean(state.search) || Object.keys(state.filters).length > 0,
    setPage: (page) => go({ ...state, page: Math.max(1, page) }),
    setSearch: (search) => go({ ...state, search: search.trim(), page: 1 }),
    setOrdering: (ordering) => go({ ...state, ordering, page: 1 }),
    setFilter: (key, value) => {
      const filters = { ...state.filters };
      if (value) filters[key] = value;
      else delete filters[key];
      go({ ...state, filters, page: 1 });
    },
    clearFilters: () => go({ ...state, search: "", filters: {}, page: 1 }),
  };
}
