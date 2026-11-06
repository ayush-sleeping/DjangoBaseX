/**
 * The DataTable standard (FRONTEND_PLATFORM § 12, BUILD_ORDER 8.3b): shift-range selection;
 * select-all escalates to query mode; a query change clears the selection; the ECHOED ordering
 * drives the arrow; skeleton rows equal the page size; every checkbox is labelled by its row.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { BulkBar } from "./BulkBar";
import { DataTable } from "./DataTable";
import { nextOrdering, parseOrdering } from "./ordering";
import { pageWindow } from "./Pager";
import { bulkTarget, EMPTY_SELECTION, type Selection, selectedCount, toggleRow } from "./selection";
import type { DataTableColumn } from "./types";

type Row = { id: string; name: string };
const ROWS: Row[] = ["a", "b", "c", "d", "e"].map((id) => ({ id, name: `Row ${id.toUpperCase()}` }));
const COLUMNS: DataTableColumn<Row>[] = [
  { id: "name", kind: "identifier", header: "Name", cell: (r) => r.name, sortKey: "name" },
  { id: "plain", kind: "data", header: "Plain", cell: () => "x" },
];
const getRowId = (r: Row) => r.id;
const getRowLabel = (r: Row) => r.name;

function Harness({ queryIdentity = "q1", total = 50, onSelection }: { queryIdentity?: string; total?: number; onSelection?: (s: Selection) => void }) {
  const [selection, setSelection] = useState<Selection>(EMPTY_SELECTION);
  const change = (next: Selection) => {
    setSelection(next);
    onSelection?.(next);
  };
  return (
    <>
      <BulkBar selection={selection} onChange={change} total={total} pageIds={ROWS.map(getRowId)} noun="rows" />
      <DataTable caption="Rows" columns={COLUMNS} rows={ROWS} getRowId={getRowId} getRowLabel={getRowLabel} selection={{ value: selection, onChange: change }} queryIdentity={queryIdentity} />
    </>
  );
}

describe("selection", () => {
  it("labels every checkbox by its row", () => {
    render(<Harness />);
    expect(screen.getByRole("checkbox", { name: "Select Row C" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select all rows on this page" })).toBeInTheDocument();
  });

  it("shift-click selects the range since the last click", async () => {
    const user = userEvent.setup();
    const seen = vi.fn();
    render(<Harness onSelection={seen} />);
    await user.click(screen.getByRole("checkbox", { name: "Select Row B" }));
    await user.keyboard("{Shift>}");
    await user.click(screen.getByRole("checkbox", { name: "Select Row D" }));
    await user.keyboard("{/Shift}");
    const last = seen.mock.calls.at(-1)![0] as Selection;
    expect(last.mode === "ids" && [...last.ids].sort()).toEqual(["b", "c", "d"]);
    expect(screen.getByText("3 selected")).toBeInTheDocument();
  });

  it("selecting the page offers every matching row, and escalates to query mode", async () => {
    const user = userEvent.setup();
    const seen = vi.fn();
    render(<Harness onSelection={seen} total={1337} />);
    await user.click(screen.getByRole("checkbox", { name: "Select all rows on this page" }));
    // The count is grouped by the locale (ICU {total, number}): "1,337" in the shipped one.
    await user.click(screen.getByRole("button", { name: /^Select all 1\D?337 matching$/ }));
    const last = seen.mock.calls.at(-1)![0] as Selection;
    expect(last.mode).toBe("query");
    expect(screen.getByText(/^All 1\D?337 matching rows selected$/)).toBeInTheDocument();
    // Unticking one row in query mode excludes it, and the bulk target re-runs the query.
    await user.click(screen.getByRole("checkbox", { name: "Select Row A" }));
    const after = seen.mock.calls.at(-1)![0] as Selection;
    expect(bulkTarget(after, { search: "x" })).toEqual({ mode: "query", query: { search: "x" }, excludeIds: ["a"] });
    expect(selectedCount(after, 1337)).toBe(1336);
  });

  it("a change of query clears the selection", async () => {
    const user = userEvent.setup();
    const seen = vi.fn();
    const { rerender } = render(<Harness onSelection={seen} queryIdentity="search=a" />);
    await user.click(screen.getByRole("checkbox", { name: "Select Row A" }));
    rerender(<Harness onSelection={seen} queryIdentity="search=b" />);
    expect(seen.mock.calls.at(-1)![0]).toEqual(EMPTY_SELECTION);
    expect(screen.getByRole("checkbox", { name: "Select Row A" })).not.toBeChecked();
  });

  it("toggleRow without an anchor on the page selects only the clicked row", () => {
    const s = toggleRow(EMPTY_SELECTION, "c", ["a", "b", "c"], true);
    expect(s.mode === "ids" && [...s.ids]).toEqual(["c"]);
  });
});

describe("sorting", () => {
  it("draws the arrow from the ordering the API echoed, not from what was asked", () => {
    const { rerender } = render(<DataTable caption="Rows" columns={COLUMNS} rows={ROWS} getRowId={getRowId} getRowLabel={getRowLabel} ordering={null} onSortChange={() => undefined} />);
    const header = () => screen.getByRole("columnheader", { name: /Name/ });
    expect(header()).not.toHaveAttribute("aria-sort");
    rerender(<DataTable caption="Rows" columns={COLUMNS} rows={ROWS} getRowId={getRowId} getRowLabel={getRowLabel} ordering="-name" onSortChange={() => undefined} />);
    expect(header()).toHaveAttribute("aria-sort", "descending");
  });

  it("only a column with a sortKey is clickable, and clicks cycle asc → desc → default", async () => {
    const user = userEvent.setup();
    const onSort = vi.fn();
    render(<DataTable caption="Rows" columns={COLUMNS} rows={ROWS} getRowId={getRowId} getRowLabel={getRowLabel} ordering="name" onSortChange={onSort} />);
    expect(within(screen.getByRole("columnheader", { name: "Plain" })).queryByRole("button")).toBeNull();
    await user.click(within(screen.getByRole("columnheader", { name: /Name/ })).getByRole("button"));
    expect(onSort).toHaveBeenCalledWith("-name");
    expect(nextOrdering(parseOrdering("-name"), "name")).toBeNull();
    expect(nextOrdering(parseOrdering("email"), "name")).toBe("name");
  });

  it("warns in development about a sortable column without a sortKey", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    render(<DataTable caption="Rows" columns={[{ id: "bad", kind: "data", header: "Bad", cell: () => "", sortable: true }]} rows={ROWS} getRowId={getRowId} getRowLabel={getRowLabel} />);
    expect(warn).toHaveBeenCalledWith(expect.stringContaining('"bad" is sortable but has no sortKey'));
    warn.mockRestore();
  });
});

describe("loading and paging", () => {
  it("draws exactly pageSize skeleton rows while loading", () => {
    const { container } = render(<DataTable caption="Rows" columns={COLUMNS} rows={[]} getRowId={getRowId} getRowLabel={getRowLabel} loading pageSize={7} />);
    expect(container.querySelectorAll("tr[data-skeleton]")).toHaveLength(7);
  });

  it("truncates the page list around the current page", () => {
    expect(pageWindow(1, 5)).toEqual([1, 2, 3, 4, 5]);
    expect(pageWindow(10, 20)).toEqual([1, "gap", 9, 10, 11, "gap", 20]);
    expect(pageWindow(3, 20)).toEqual([1, 2, 3, 4, "gap", 20]);
  });
});
