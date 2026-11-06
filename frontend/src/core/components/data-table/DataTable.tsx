"use client";

/**
 * The only list renderer (FRONTEND_PLATFORM § 12, BUILD_ORDER 8.3b). Server-driven: it draws the
 * rows the API returned, in the order it returned them. It never sorts, filters or pages itself.
 *
 * - The sort arrow comes from the ordering the API ECHOED, so an ignored sort draws no arrow.
 * - Selection (optional) is checkbox-only, with shift-click ranges and a query-mode "select all"
 *   (see selection.ts). A change of `queryIdentity` clears it.
 * - While loading it draws exactly pageSize skeleton rows, so the layout does not jump.
 * - The identifier column sticks left and actions stick right, so a row's identity and actions stay
 *   reachable at any width.
 * - Every checkbox is labelled from getRowLabel: "Select Ada Lovelace", not "Select row".
 *
 * TanStack Table v9 (core features only) owns column/row modelling. This file is the only importer,
 * so modules depend on DataTableColumn, never on the engine.
 */
import { createColumnHelper, type RowData, tableFeatures, useTable } from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import { type ReactNode, useEffect, useMemo, useRef } from "react";

import { list as listDefaults } from "@/core/lib/config/defaults";

import { nextOrdering, parseOrdering } from "./ordering";
import { EMPTY_SELECTION, isSelected, pageState, type Selection, toggleRow, togglePage } from "./selection";
import type { Breakpoint, DataTableColumn } from "./types";

const features = tableFeatures({});

// Literal class names: Tailwind only emits classes it finds whole in source.
const HIDE_BELOW: Record<Breakpoint, string> = {
  sm: "hidden sm:table-cell",
  md: "hidden md:table-cell",
  lg: "hidden lg:table-cell",
  xl: "hidden xl:table-cell",
};
const ALIGN = { left: "text-left", center: "text-center", right: "text-right" } as const;
const SEAM_LEFT = "shadow-[inset_-1px_0_0_var(--border)]";
const SEAM_RIGHT = "shadow-[inset_1px_0_0_var(--border)]";

export type DataTableSelection = {
  value: Selection;
  onChange: (next: Selection) => void;
};

export type DataTableProps<T extends RowData> = {
  columns: readonly DataTableColumn<T>[];
  rows: readonly T[];
  getRowId: (row: T) => string;
  /** The row's human name, for accessible labels ("Select {label}", "Edit {label}"). */
  getRowLabel: (row: T) => string;
  /** The `ordering` the API echoed back (null: the API's default or it echoes none). */
  ordering?: string | null;
  onSortChange?: (ordering: string | null) => void;
  selection?: DataTableSelection;
  /** Changes whenever the list's query changes (search, filters, ordering): clears the selection. */
  queryIdentity?: string;
  /** First load: skeleton rows. */
  loading?: boolean;
  /** A background refetch: rows stay, marked busy. */
  fetching?: boolean;
  pageSize?: number;
  /** Rendered in place of the body when there are no rows (the shell supplies the right variant). */
  empty?: ReactNode;
  /** The accessible name of the table. */
  caption: string;
};

function stickyFor<T>(column: DataTableColumn<T>): "left" | "right" | undefined {
  return column.sticky ?? (column.kind === "identifier" ? "left" : column.kind === "actions" ? "right" : undefined);
}

function cellClass<T>(column: DataTableColumn<T>, withSelection: boolean): string {
  const sticky = stickyFor(column);
  return [
    "px-3 py-2 align-middle bg-inherit",
    ALIGN[column.align ?? (column.kind === "actions" ? "right" : "left")],
    column.hideBelow ? HIDE_BELOW[column.hideBelow] : "",
    sticky === "left" ? `sticky z-10 ${withSelection ? "left-10" : "left-0"} ${SEAM_LEFT}` : "",
    sticky === "right" ? `sticky right-0 z-10 ${SEAM_RIGHT}` : "",
  ]
    .filter(Boolean)
    .join(" ");
}

function SortIcon({ active, desc }: { active: boolean; desc: boolean }) {
  if (!active) return <ArrowUpDown aria-hidden className="size-3.5 opacity-40" />;
  return desc ? <ArrowDown aria-hidden className="size-3.5" /> : <ArrowUp aria-hidden className="size-3.5" />;
}

function Checkbox({
  checked,
  indeterminate = false,
  label,
  onToggle,
}: {
  checked: boolean;
  indeterminate?: boolean;
  label: string;
  onToggle: (shift: boolean) => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = indeterminate;
  }, [indeterminate]);
  return (
    <input
      ref={ref}
      type="checkbox"
      aria-label={label}
      checked={checked}
      // The click carries shiftKey; onChange does not. Controlled, so onChange only satisfies React.
      onChange={() => undefined}
      onClick={(event) => onToggle(event.shiftKey)}
      className="size-4 accent-primary"
    />
  );
}

const EMPTY_ROWS: never[] = [];

export function DataTable<T extends RowData>({
  columns,
  rows,
  getRowId,
  getRowLabel,
  ordering = null,
  onSortChange,
  selection,
  queryIdentity,
  loading = false,
  fetching = false,
  pageSize = listDefaults.pageSize,
  empty,
  caption,
}: DataTableProps<T>) {
  const sort = parseOrdering(ordering);
  const withSelection = selection !== undefined;
  const data = rows.length ? (rows as T[]) : (EMPTY_ROWS as T[]);

  const tableColumns = useMemo(() => {
    const helper = createColumnHelper<typeof features, T>();
    return helper.columns(columns.map((column) => helper.display({ id: column.id, header: () => column.header, cell: (ctx) => column.cell(ctx.row.original) })));
  }, [columns]);

  const table = useTable({ features, columns: tableColumns, data, getRowId: (row: T) => getRowId(row) });
  const pageIds = useMemo(() => data.map(getRowId), [data, getRowId]);

  // A different query is a different set of rows: never carry a selection across it.
  const lastQuery = useRef(queryIdentity);
  const onSelectionChange = selection?.onChange;
  useEffect(() => {
    if (lastQuery.current !== queryIdentity) {
      lastQuery.current = queryIdentity;
      onSelectionChange?.(EMPTY_SELECTION);
    }
  }, [queryIdentity, onSelectionChange]);

  useEffect(() => {
    if (process.env.NODE_ENV === "production") return;
    for (const column of columns) {
      if (column.sortable && !column.sortKey) {
        console.warn(`DataTable: column "${column.id}" is sortable but has no sortKey; it will not sort.`);
      }
    }
  }, [columns]);

  const byId = new Map(columns.map((column) => [column.id, column]));
  const page = selection ? pageState(selection.value, pageIds) : "none";

  return (
    <div className="min-h-0 overflow-auto rounded-lg border border-border bg-card" aria-busy={loading || fetching || undefined}>
      <table className={`w-full border-collapse text-sm ${fetching && !loading ? "opacity-70" : ""}`}>
        <caption className="sr-only">{caption}</caption>
        <thead className="sticky top-0 z-20 bg-muted text-xs uppercase tracking-wide text-muted-foreground">
          {table.getHeaderGroups().map((group) => (
            <tr key={group.id} className="bg-muted">
              {withSelection ? (
                <th scope="col" className={`sticky left-0 z-10 w-10 bg-inherit px-3 py-2 ${SEAM_LEFT}`}>
                  <Checkbox
                    checked={page === "all"}
                    indeterminate={page === "some"}
                    label="Select all rows on this page"
                    onToggle={() => selection.onChange(togglePage(selection.value, pageIds))}
                  />
                </th>
              ) : null}
              {group.headers.map((header) => {
                const column = byId.get(header.column.id)!;
                const sortable = Boolean(column.sortKey && onSortChange);
                const active = sortable && sort?.key === column.sortKey;
                return (
                  <th
                    key={header.id}
                    scope="col"
                    title={column.headerTooltip}
                    style={column.width ? { width: column.width } : undefined}
                    aria-sort={active ? (sort!.desc ? "descending" : "ascending") : undefined}
                    className={`font-medium ${cellClass(column, withSelection)}`}
                  >
                    {sortable ? (
                      <button
                        type="button"
                        className="inline-flex items-center gap-1 uppercase tracking-wide hover:text-foreground"
                        onClick={() => onSortChange!(nextOrdering(sort, column.sortKey!))}
                      >
                        <table.FlexRender header={header} />
                        <SortIcon active={active} desc={Boolean(sort?.desc)} />
                      </button>
                    ) : (
                      <table.FlexRender header={header} />
                    )}
                  </th>
                );
              })}
            </tr>
          ))}
        </thead>
        <tbody className="divide-y divide-border">
          {loading
            ? Array.from({ length: pageSize }, (_, i) => (
                <tr key={`skeleton-${i}`} data-skeleton className="bg-card">
                  {withSelection ? <td className="w-10 px-3 py-2" /> : null}
                  {columns.map((column) => (
                    <td key={column.id} className={cellClass(column, withSelection)}>
                      <span className="block h-4 w-3/4 animate-pulse rounded bg-muted" />
                    </td>
                  ))}
                </tr>
              ))
            : table.getRowModel().rows.map((row) => {
                const id = row.id;
                const label = getRowLabel(row.original);
                const ticked = selection ? isSelected(selection.value, id) : false;
                return (
                  <tr key={id} aria-selected={selection ? ticked : undefined} className={`bg-card hover:bg-accent ${ticked ? "bg-accent" : ""}`}>
                    {withSelection ? (
                      <td className={`sticky left-0 z-10 w-10 bg-inherit px-3 py-2 ${SEAM_LEFT}`}>
                        <Checkbox
                          checked={ticked}
                          label={`Select ${label}`}
                          onToggle={(shift) => selection.onChange(toggleRow(selection.value, id, pageIds, shift))}
                        />
                      </td>
                    ) : null}
                    {row.getAllCells().map((cell) => (
                      <td key={cell.id} className={cellClass(byId.get(cell.column.id)!, withSelection)}>
                        <table.FlexRender cell={cell} />
                      </td>
                    ))}
                  </tr>
                );
              })}
        </tbody>
      </table>
      {!loading && rows.length === 0 && empty ? <div className="p-4">{empty}</div> : null}
    </div>
  );
}
