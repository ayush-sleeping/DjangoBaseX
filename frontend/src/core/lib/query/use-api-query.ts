"use client";

/**
 * The load-state contract (FRONTEND_PLATFORM.md § 5) over TanStack Query (§ 4). Failure, loading,
 * empty and data are DISJOINT, and a page renders them in that order: error → loading → empty →
 * data. A failed fetch never renders as an authoritative "nothing here".
 *
 * Keys arrive from a defineKeys factory as [root, kind, ...params]; the active scope context is
 * inserted here, so a caller cannot forget it: [root, kind, context, ...params].
 */
import {
  type QueryKey,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
  type UseMutationOptions,
  type UseQueryOptions,
} from "@tanstack/react-query";
import { useEffect } from "react";

import type { Page } from "@/core/lib/api";

import { notifyRefreshFailed } from "./refresh-failed";

/** The active scope (tenant, project). Core names none, so it is {} until a module provides one. */
function useScopeContext(): Record<string, unknown> {
  return EMPTY_SCOPE;
}
const EMPTY_SCOPE: Record<string, unknown> = {};

export function scopedKey(key: QueryKey, context: Record<string, unknown>): QueryKey {
  const [root, kind, ...params] = key;
  return [root, kind, context, ...params];
}

export type ApiQueryOptions<T> = Omit<UseQueryOptions<T>, "queryKey" | "queryFn"> & {
  /** Form-seeding queries never refetch on reconnect or focus: a reconnect would replace a draft. */
  purpose?: "form-seed";
};

export type ApiQueryResult<T> = {
  data: T | undefined;
  /** First load only. */
  isLoading: boolean;
  /** Any request in flight, first load included. */
  isFetching: boolean;
  isError: boolean;
  isSuccess: boolean;
  error: unknown;
  /** Failed AND nothing to show: the only state that renders an error surface. */
  showError: boolean;
  /** Awaitable, never rejects. */
  refetch: () => Promise<void>;
  queryKey: QueryKey;
};

/** Optional settings are spread in only when defined: an explicit `undefined` would override a default with 0. */
function defined<T extends object>(options: T): Partial<T> {
  return Object.fromEntries(Object.entries(options).filter(([, v]) => v !== undefined)) as Partial<T>;
}

export function useApiQuery<T>(
  key: QueryKey,
  queryFn: (signal: AbortSignal) => Promise<T>,
  options: ApiQueryOptions<T> = {},
): ApiQueryResult<T> {
  const { purpose, ...rest } = options;
  const queryKey = scopedKey(key, useScopeContext());
  const result = useQuery<T>({
    queryKey,
    queryFn: ({ signal }) => queryFn(signal),
    ...(purpose === "form-seed" ? { refetchOnReconnect: false, refetchOnWindowFocus: false } : {}),
    ...defined(rest),
  });
  useEffect(() => {
    if (result.isError && result.data !== undefined) notifyRefreshFailed(result.error);
  }, [result.isError, result.error, result.data]);
  return {
    data: result.data,
    isLoading: result.isPending && result.fetchStatus === "fetching",
    isFetching: result.isFetching,
    isError: result.isError,
    isSuccess: result.isSuccess,
    error: result.error,
    showError: result.isError && result.data === undefined,
    refetch: async () => {
      try {
        await result.refetch();
      } catch {
        /* a refetch never rejects: the error is on the result */
      }
    },
    queryKey,
  };
}

export type ListErrorProps = { error: unknown; retry: () => Promise<void> };

export type ApiListResult<T> = ApiQueryResult<Page<T>> & {
  items: T[];
  count: number;
  /** isSuccess && empty — never `!isLoading && …`, because a disabled query is neither loading nor errored. */
  isEmpty: boolean;
  listErrorProps: ListErrorProps;
};

export function useApiList<T>(
  key: QueryKey,
  queryFn: (signal: AbortSignal) => Promise<Page<T>>,
  options: ApiQueryOptions<Page<T>> = {},
): ApiListResult<T> {
  const q = useApiQuery<Page<T>>(key, queryFn, options);
  const items = q.data?.results ?? [];
  return {
    ...q,
    items,
    count: q.data?.count ?? 0,
    isEmpty: q.isSuccess && items.length === 0,
    listErrorProps: { error: q.error, retry: q.refetch },
  };
}

/** Invalidate a resource by prefix AND every query that declares it in meta.dependsOn. */
export async function invalidateResource(client: QueryClient, root: string): Promise<void> {
  await client.invalidateQueries({
    predicate: (query) => {
      if (query.queryKey[0] === root) return true;
      const dependsOn = (query.meta as { dependsOn?: unknown } | undefined)?.dependsOn;
      return Array.isArray(dependsOn) && dependsOn.includes(root);
    },
  });
}

export type ApiMutationOptions<TData, TVariables> = Omit<
  UseMutationOptions<TData, unknown, TVariables>,
  "mutationFn"
> & {
  mutationFn: (variables: TVariables) => Promise<TData>;
} & (
    | { invalidates: readonly [string, ...string[]]; reason?: string }
    | { invalidates: readonly []; reason: string }
  );

/** Mutations invalidate; `invalidates` is required so a missing one is a type error, not stale data. */
export function useApiMutation<TData, TVariables = void>(options: ApiMutationOptions<TData, TVariables>) {
  const client = useQueryClient();
  const { invalidates, reason, onSuccess, ...rest } = options;
  void reason; // documentation for the reviewer, not behaviour
  return useMutation<TData, unknown, TVariables>({
    ...rest,
    onSuccess: async (data, variables, context, mutation) => {
      await Promise.all(invalidates.map((root) => invalidateResource(client, root)));
      await onSuccess?.(data, variables, context, mutation);
    },
  });
}
