"use client";

/**
 * The Index shell (FRONTEND_PLATFORM § 11): title row → toolbar → selection bar → DataTable →
 * pager. A module supplies columns, the list query and its actions; it never supplies layout, so
 * every list in every product pages, sorts, selects, fails and empties the same way.
 *
 * Disjoint states, in order (§ 5): failed (ListLoadError, never "nothing here") → first load
 * (skeleton rows) → empty — "none yet" (with a create CTA, if permitted) or "filtered" (with Clear
 * filters) — → rows. The row count is the pager's alone.
 */
import type { ReactNode } from "react";

import { useEnrolmentRedirect } from "./use-enrolment-redirect";

import { Button } from "@/core/components/Button";
import {
  BulkBar,
  DataTable,
  type DataTableColumn,
  Pager,
  type RowData,
  type Selection,
} from "@/core/components/data-table";
import { EmptyState } from "@/core/components/EmptyState";
import { ListLoadError } from "@/core/components/ListLoadError";
import { list as listDefaults } from "@/core/lib/config/defaults";
import { useT } from "@/core/lib/i18n";
import type { ListErrorProps } from "@/core/lib/query/use-api-query";

/** The slice of useApiList the shell reads. */
export type IndexList<T> = {
  items: T[];
  count: number;
  isLoading: boolean;
  isFetching: boolean;
  isEmpty: boolean;
  showError: boolean;
  listErrorProps: ListErrorProps;
};

export type ResourceIndexProps<T extends RowData> = {
  /** "<module>.<resource>.index", rendered as data-page for e2e selectors. */
  pageKey: string;
  title: string;
  /** Plural noun, already translated: "users", "orders". Used by the pager, the empty state and the error. */
  noun: string;
  description?: ReactNode;
  /** Header actions: New, Export… each already permission-gated by the caller. */
  actions?: ReactNode;
  /** Search and the page-scope controls. */
  toolbar?: ReactNode;
  columns: readonly DataTableColumn<T>[];
  list: IndexList<T>;
  getRowId: (row: T) => string;
  getRowLabel: (row: T) => string;
  page: number;
  onPage: (page: number) => void;
  pageSize?: number;
  /** The ordering the API echoed back. */
  ordering?: string | null;
  onSortChange?: (ordering: string | null) => void;
  /** The list's query, serialised: a change clears any selection. */
  queryIdentity: string;
  /** Search or filters narrow the list: an empty result is "filtered", not "none yet". */
  filtered: boolean;
  onClearFilters?: () => void;
  /** "None yet" call to action — pass it only when the user may create. */
  emptyAction?: ReactNode;
  emptyBody?: ReactNode;
  selection?: { value: Selection; onChange: (next: Selection) => void };
  /** Bulk actions shown in the selection bar. */
  bulkActions?: ReactNode;
  /** Modals the index opens (create, edit) — rendered here so filters and scroll survive. */
  children?: ReactNode;
};

export function ResourceIndex<T extends RowData>({
  pageKey,
  title,
  noun,
  description,
  actions,
  toolbar,
  columns,
  list,
  getRowId,
  getRowLabel,
  page,
  onPage,
  pageSize = listDefaults.pageSize,
  ordering,
  onSortChange,
  queryIdentity,
  filtered,
  onClearFilters,
  emptyAction,
  emptyBody,
  selection,
  bulkActions,
  children,
}: ResourceIndexProps<T>) {
  const t = useT("shells.index");
  useEnrolmentRedirect(list.showError ? list.listErrorProps.error : null);
  const empty = list.isEmpty ? (
    filtered ? (
      <EmptyState
        variant="filtered"
        title={t("filteredEmpty", { noun })}
        action={onClearFilters ? <Button variant="secondary" onClick={onClearFilters}>{t("clearFilters")}</Button> : undefined}
      />
    ) : (
      <EmptyState variant="none" title={t("noneYet", { noun })} body={emptyBody} action={emptyAction} />
    )
  ) : null;
  const showPager = !list.showError && !list.isLoading && list.count > 0;

  return (
    <main data-page={pageKey} className="mx-auto flex min-h-0 w-full max-w-6xl flex-1 flex-col gap-4 p-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
          {description ? <p className="mt-1 text-sm text-muted-foreground">{description}</p> : null}
        </div>
        {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
      </header>
      {toolbar ? <div className="flex flex-wrap items-center gap-3">{toolbar}</div> : null}
      {selection ? (
        <BulkBar selection={selection.value} onChange={selection.onChange} total={list.count} pageIds={list.items.map(getRowId)} noun={noun}>
          {bulkActions}
        </BulkBar>
      ) : null}
      {list.showError ? (
        <ListLoadError {...list.listErrorProps} resource={noun} />
      ) : (
        <>
          {showPager && list.count > pageSize ? <Pager page={page} count={list.count} onPage={onPage} pageSize={pageSize} noun={noun} disabled={list.isFetching} /> : null}
          <DataTable
            caption={title}
            columns={columns}
            rows={list.items}
            getRowId={getRowId}
            getRowLabel={getRowLabel}
            ordering={ordering}
            onSortChange={onSortChange}
            selection={selection}
            queryIdentity={queryIdentity}
            loading={list.isLoading}
            fetching={list.isFetching}
            pageSize={pageSize}
            empty={empty}
          />
          {showPager ? <Pager page={page} count={list.count} onPage={onPage} pageSize={pageSize} noun={noun} disabled={list.isFetching} /> : null}
        </>
      )}
      {children}
    </main>
  );
}
