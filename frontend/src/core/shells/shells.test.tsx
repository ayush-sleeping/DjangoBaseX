/**
 * The shells' contracts (FRONTEND_PLATFORM § 11, § 15; BUILD_ORDER 8.3b).
 */
import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useForm } from "react-hook-form";
import { describe, expect, it, vi } from "vitest";

import { ConfirmHost } from "@/core/components/confirm";
import type { DataTableColumn } from "@/core/components/data-table";
import { FormField } from "@/core/components/form/FormField";
import { ApiError } from "@/core/lib/api/errors";

import { applyServerErrors, dirtyValues, FORM_ERROR } from "./form-errors";
import { ResourceForm } from "./ResourceForm";
import { type IndexList, ResourceIndex } from "./ResourceIndex";
import { MetaCard, ResourceShow } from "./ResourceShow";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

const validation = (raw: { path: string; message: string }[], nonField: string[] = [], fields = raw.map((f) => ({ ...f, code: "invalid" }))) =>
  new ApiError({ kind: "validation", status: 400, code: "invalid", method: "POST", path: "/api/x/", requestId: "r1", body: null, details: null, fields, nonField });

/** The form-level error, typed independently of the test form's field names. */
const rootError = (form: { getFieldState: (name: never) => { error?: { message?: string } } }) =>
  form.getFieldState(FORM_ERROR as never).error?.message;

describe("applyServerErrors", () => {
  it("puts known paths on their fields and unknown ones at form level, never dropping one", () => {
    const { result } = renderHook(() => useForm({ defaultValues: { email: "", lines: [{ qty: 1 }] } }));
    const form = result.current;
    let applied = 0;
    act(() => {
      applied = applyServerErrors(form, validation([
        { path: "email", message: "Taken." },
        { path: "lines.0.qty", message: "Too many." },
        { path: "secret_field", message: "Bad." },
      ], ["Try later."]));
    });
    expect(applied).toBe(2);
    expect(form.getFieldState("email").error?.message).toBe("Taken.");
    expect(form.getFieldState("lines.0.qty").error?.message).toBe("Too many.");
    expect(rootError(form)).toBe("secret_field: Bad. Try later.");
  });

  it("turns a non-validation failure into a form-level message", () => {
    const { result } = renderHook(() => useForm({ defaultValues: { name: "" } }));
    act(() => void applyServerErrors(result.current, new Error("network")));
    expect(rootError(result.current)).toMatch(/Something went wrong/);
  });

  it("dirtyValues keeps only changed fields", () => {
    expect(dirtyValues({ a: 1, b: 2, c: 3 }, { b: true })).toEqual({ b: 2 });
  });
});

function NameForm({ onSubmit, layout = "page", onClose }: { onSubmit: (v: { name: string }, changed: Partial<{ name: string }>) => Promise<void>; layout?: "page" | "modal"; onClose?: () => void }) {
  const form = useForm({ defaultValues: { name: "Ada" } });
  return (
    <ResourceForm pageKey="test.thing.form" form={form} resource="thing" record={{ name: "Ada" }} onSubmit={onSubmit} layout={layout} open onClose={onClose}>
      <FormField control={form.control} name="name" kind="text" label="Name" />
    </ResourceForm>
  );
}

describe("ResourceForm", () => {
  it("names the record in edit mode, and Save waits until something changed", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<NameForm onSubmit={onSubmit} />);
    expect(screen.getByRole("heading", { name: "Edit Ada" })).toBeInTheDocument();
    const save = screen.getByRole("button", { name: "Save changes" });
    expect(save).toBeDisabled();
    await user.type(screen.getByLabelText("Name"), " L");
    expect(save).toBeEnabled();
    await user.click(save);
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({ name: "Ada L" }, { name: "Ada L" }));
  });

  it("shows a server field error once, on the field, and counts it in the footer", async () => {
    const user = userEvent.setup();
    render(<NameForm onSubmit={() => Promise.reject(validation([{ path: "name", message: "Too short." }]))} />);
    await user.type(screen.getByLabelText("Name"), "!");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findAllByText("Too short.")).toHaveLength(1);
    expect(screen.getByText("1 field needs attention.")).toBeInTheDocument();
  });

  it("asks before discarding a dirty modal", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <>
        <ConfirmHost />
        <NameForm onSubmit={vi.fn()} layout="modal" onClose={onClose} />
      </>,
    );
    await user.type(screen.getByLabelText("Name"), "x");
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(await screen.findByText("Discard your changes?")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Discard" }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });
});

type Row = { id: string; name: string };
const COLUMNS: DataTableColumn<Row>[] = [{ id: "name", kind: "identifier", header: "Name", cell: (r) => r.name }];
const list = (over: Partial<IndexList<Row>>): IndexList<Row> => ({
  items: [], count: 0, isLoading: false, isFetching: false, isEmpty: false, showError: false,
  listErrorProps: { error: null, retry: async () => undefined }, ...over,
});
const index = (l: IndexList<Row>, filtered = false) => (
  <ResourceIndex<Row> pageKey="test.row.index" title="Rows" noun="rows" columns={COLUMNS} list={l} getRowId={(r) => r.id} getRowLabel={(r) => r.name}
    page={1} onPage={vi.fn()} queryIdentity="q" filtered={filtered} onClearFilters={vi.fn()} emptyAction={<button type="button">New row</button>} />
);

describe("ResourceIndex", () => {
  it("renders a failed load as an error, never as an empty list", () => {
    render(index(list({ showError: true, listErrorProps: { error: new Error("x"), retry: async () => undefined } })));
    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't load rows");
    expect(screen.queryByText(/No rows/)).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("distinguishes none-yet (with the create action) from filtered (with Clear filters)", () => {
    const { rerender } = render(index(list({ isEmpty: true })));
    expect(screen.getByText("No rows yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New row" })).toBeInTheDocument();
    rerender(index(list({ isEmpty: true }), true));
    expect(screen.getByText("No rows match these filters")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clear filters" })).toBeInTheDocument();
  });

  it("puts the row count in the pager and stamps data-page", () => {
    const { container } = render(index(list({ items: [{ id: "1", name: "One" }], count: 1, isEmpty: false })));
    expect(screen.getByRole("navigation", { name: "Pagination" })).toHaveTextContent("1–1 of 1 rows");
    expect(container.querySelector('[data-page="test.row.index"]')).not.toBeNull();
  });
});

describe("ResourceShow", () => {
  const state = { isLoading: false, showError: false, error: null, refetch: vi.fn() };

  it("renders the record in a 2:1 grid with a self-start sticky sidebar", () => {
    const { container } = render(
      <ResourceShow pageKey="test.row.show" noun="row" state={state} title="Row one" sidebar={<MetaCard items={[{ label: "Created", value: null }]} />}>
        <p>Body</p>
      </ResourceShow>,
    );
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Row one");
    expect(container.querySelector("aside")?.className).toMatch(/self-start/);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("shows a failure as a panel error, not a half-loaded record", () => {
    render(<ResourceShow pageKey="test.row.show" noun="row" state={{ ...state, showError: true, error: new Error("x") }} title="Row one"><p>Body</p></ResourceShow>);
    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't load this row");
    expect(screen.queryByText("Body")).toBeNull();
  });
});
