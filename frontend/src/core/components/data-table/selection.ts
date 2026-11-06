/**
 * Row selection (FRONTEND_PLATFORM § 12), as a pure reducer so its rules are tested directly.
 *
 * Two modes, never mixed:
 * - `ids`: the rows the user ticked, on any page. The checkbox is the only gesture; shift-click
 *   selects the range since the last click on this page.
 * - `query`: "Select all 1,337 matching". The bulk endpoint then re-runs the list's own query minus
 *   `excludeIds` — never a list of ids built in the browser, because two definitions of "the rows I
 *   see" drift, and the drift acts on the wrong rows.
 *
 * Any change to the list's query (search, filters, ordering) must clear the selection: the caller
 * passes the query identity, and DataTable clears when it changes.
 */
export type Selection =
  | { mode: "ids"; ids: ReadonlySet<string>; anchor: string | null }
  | { mode: "query"; excludeIds: ReadonlySet<string> };

export const EMPTY_SELECTION: Selection = { mode: "ids", ids: new Set(), anchor: null };

export type BulkTarget<Q> = { mode: "ids"; ids: string[] } | { mode: "query"; query: Q; excludeIds: string[] };

export function isSelected(selection: Selection, id: string): boolean {
  return selection.mode === "ids" ? selection.ids.has(id) : !selection.excludeIds.has(id);
}

/** How many rows the selection covers, given the list's total. */
export function selectedCount(selection: Selection, total: number): number {
  return selection.mode === "ids" ? selection.ids.size : Math.max(0, total - selection.excludeIds.size);
}

/** Tick or untick one row; with shift, apply the same state to every row between it and the anchor. */
export function toggleRow(selection: Selection, id: string, pageIds: readonly string[], shift = false): Selection {
  const target = !isSelected(selection, id);
  let range = [id];
  if (shift && selection.mode === "ids" && selection.anchor !== null) {
    const a = pageIds.indexOf(selection.anchor);
    const b = pageIds.indexOf(id);
    if (a !== -1 && b !== -1) range = pageIds.slice(Math.min(a, b), Math.max(a, b) + 1);
  }
  if (selection.mode === "query") {
    const excludeIds = new Set(selection.excludeIds);
    for (const rowId of range) {
      if (target) excludeIds.delete(rowId);
      else excludeIds.add(rowId);
    }
    return { mode: "query", excludeIds };
  }
  const ids = new Set(selection.ids);
  for (const rowId of range) {
    if (target) ids.add(rowId);
    else ids.delete(rowId);
  }
  return { mode: "ids", ids, anchor: id };
}

export type PageState = "none" | "some" | "all";

export function pageState(selection: Selection, pageIds: readonly string[]): PageState {
  const ticked = pageIds.filter((id) => isSelected(selection, id)).length;
  if (ticked === 0 || pageIds.length === 0) return "none";
  return ticked === pageIds.length ? "all" : "some";
}

/** The header checkbox: select the whole page, or clear it if all of it is selected. */
export function togglePage(selection: Selection, pageIds: readonly string[]): Selection {
  const select = pageState(selection, pageIds) !== "all";
  if (selection.mode === "query") {
    const excludeIds = new Set(selection.excludeIds);
    for (const id of pageIds) {
      if (select) excludeIds.delete(id);
      else excludeIds.add(id);
    }
    return { mode: "query", excludeIds };
  }
  const ids = new Set(selection.ids);
  for (const id of pageIds) {
    if (select) ids.add(id);
    else ids.delete(id);
  }
  return { mode: "ids", ids, anchor: null };
}

/** Escalate to every row matching the list's query. */
export function selectAllMatching(): Selection {
  return { mode: "query", excludeIds: new Set() };
}

/** What a bulk endpoint receives. */
export function bulkTarget<Q>(selection: Selection, query: Q): BulkTarget<Q> {
  return selection.mode === "ids"
    ? { mode: "ids", ids: [...selection.ids].sort() }
    : { mode: "query", query, excludeIds: [...selection.excludeIds].sort() };
}
