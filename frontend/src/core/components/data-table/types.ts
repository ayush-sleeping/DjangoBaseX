/**
 * The column contract every module writes (FRONTEND_PLATFORM § 11, § 12). Domain-neutral: an ERP
 * ledger, a CRM pipeline and a shop's orders all describe their columns with this, and none of them
 * imports the table library — only data-table/ does, so the engine can change behind it.
 */
import type { ReactNode } from "react";

/**
 * A column's place in the fixed order: selection → identifier → status → data… → updated → actions.
 * The DataTable draws selection itself; modules declare the rest, and module-contract.test.ts checks
 * the order in every columns.tsx.
 */
export type ColumnKind = "identifier" | "status" | "data" | "updated" | "actions";

export type Breakpoint = "sm" | "md" | "lg" | "xl";

export type DataTableColumn<T> = {
  /** Stable id; used for keys and the dev warning. */
  id: string;
  kind: ColumnKind;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  /**
   * The API `ordering` value this column sorts by. Set it ONLY when the endpoint's ordering
   * allow-list accepts it: an arrow that does nothing is a lie on the screen.
   */
  sortKey?: string;
  /** Declares intent; a sortable column without a sortKey warns in development and fails a test. */
  sortable?: boolean;
  /** Hidden below this breakpoint (secondary data on narrow screens). */
  hideBelow?: Breakpoint;
  /** Sticky to an edge; identifier and actions default to start and end (logical: RTL mirrors). */
  sticky?: "start" | "end";
  align?: "start" | "center" | "end";
  /** A CSS width, e.g. "12rem". */
  width?: string;
  headerTooltip?: string;
};

/** The ordering the API echoed back, parsed: the arrow is drawn from this, not from the URL. */
export type SortState = { key: string; desc: boolean } | null;
