/**
 * The mandatory primitives behave as their contracts say (FRONTEND_PLATFORM § 13, BUILD_ORDER 8.3a).
 */
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useForm } from "react-hook-form";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { iconFor, ICONS, isIconName } from "@/core/icons/registry";

import { confirm, ConfirmHost } from "./confirm";
import { FormField, fieldKinds, registerFieldKind } from "./form/FormField";
import { SearchInput } from "./SearchInput";
import { matchOptions, Select } from "./Select";
import { StatusPill } from "./StatusPill";
import { dismissToast, resetToasts, toast, Toaster } from "./toast";

describe("confirm()", () => {
  it("rejects loudly when no host is mounted, never hangs", async () => {
    await expect(confirm({ title: "Sure?" })).rejects.toThrow(/ConfirmHost/);
  });

  it("resolves true on confirm and false on cancel", async () => {
    const user = userEvent.setup();
    render(<ConfirmHost />);
    let answer: Promise<boolean>;
    act(() => {
      answer = confirm({ title: "Deactivate Ada?", confirmLabel: "Deactivate", tone: "danger" });
    });
    await user.click(await screen.findByRole("button", { name: "Deactivate" }));
    await expect(answer!).resolves.toBe(true);

    act(() => {
      answer = confirm({ title: "Again?" });
    });
    await user.click(await screen.findByRole("button", { name: "Cancel" }));
    await expect(answer!).resolves.toBe(false);
  });

  it("a newer question cancels the older one", async () => {
    render(<ConfirmHost />);
    let first: Promise<boolean>;
    act(() => {
      first = confirm({ title: "One" });
      void confirm({ title: "Two" });
    });
    await expect(first!).resolves.toBe(false);
    expect(await screen.findByText("Two")).toBeInTheDocument();
  });
});

describe("toast()", () => {
  beforeEach(() => resetToasts());
  afterEach(() => vi.useRealTimers());

  it("is callable outside React and shows in the one Toaster", async () => {
    render(<Toaster />);
    act(() => void toast("Saved", { tone: "ok" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Saved");
  });

  it("errors stay until dismissed and are announced as alerts", async () => {
    render(<Toaster />);
    let id = 0;
    act(() => {
      id = toast("Failed", { tone: "err" });
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("Failed");
    act(() => dismissToast(id));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });

  it("others time out", () => {
    vi.useFakeTimers();
    render(<Toaster />);
    act(() => void toast("Gone soon", { duration: 1000 }));
    expect(screen.getByText("Gone soon")).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(1001));
    expect(screen.queryByText("Gone soon")).toBeNull();
  });
});

describe("Select", () => {
  const options = [
    { value: "a", label: "Administrator" },
    { value: "s", label: "Staff" },
    { value: "v", label: "Viewer" },
  ];

  it("searches by label or value", () => {
    expect(matchOptions(options, "sta").map((o) => o.value)).toEqual(["s"]);
    expect(matchOptions(options, "V").map((o) => o.value)).toEqual(["v"]);
    expect(matchOptions(options, "").length).toBe(3);
  });

  it("is a combobox you can type into and choose from", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Select label="Role" options={options} value={null} onChange={onChange} />);
    await user.type(screen.getByRole("combobox", { name: "Role" }), "view");
    await user.click(await screen.findByRole("option", { name: "Viewer" }));
    expect(onChange).toHaveBeenCalledWith("v");
  });
});

describe("StatusPill", () => {
  it("renders the shared tone for a known status", () => {
    render(<StatusPill status="users.user.deactivated" />);
    expect(screen.getByText("Deactivated").closest("[data-tone]")).toHaveAttribute("data-tone", "err");
  });

  it("renders the dashed not-set chip for an unknown status, never a guessed colour", () => {
    render(<StatusPill status="nope.nope" />);
    expect(screen.getByText("Not set")).not.toHaveAttribute("data-tone");
  });
});

describe("FormField", () => {
  function Probe({ error }: { error?: string }) {
    const form = useForm<{ email: string; admin: boolean }>({ defaultValues: { email: "", admin: false } });
    if (error && !form.formState.errors.email) form.setError("email", { message: error });
    return (
      <form>
        <FormField control={form.control} name="email" kind="email" label="Email" required />
        <FormField control={form.control} name="admin" kind="switch" label="Administrator" />
      </form>
    );
  }

  it("labels the control and marks required with an asterisk and sr-only text", () => {
    render(<Probe />);
    expect(screen.getByLabelText(/Email/)).toHaveAttribute("type", "email");
    expect(screen.getByText("(required)")).toHaveClass("sr-only");
    expect(screen.getByRole("switch", { name: /Administrator/ })).toBeInTheDocument();
  });

  it("shows the error once, on the field, wired by aria-describedby", () => {
    render(<Probe error="Enter a valid address." />);
    const input = screen.getByLabelText(/Email/);
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(screen.getAllByText("Enter a valid address.")).toHaveLength(1);
    expect(input.getAttribute("aria-describedby")).toContain(screen.getByText("Enter a valid address.").id);
  });

  it("refuses an unknown kind and a duplicate registration", () => {
    expect(fieldKinds()).toEqual(expect.arrayContaining(["email", "select", "switch", "text"]));
    expect(() => registerFieldKind("text", () => null)).toThrow(/already registered/);
  });
});

describe("SearchInput", () => {
  it("debounces and ignores terms below the minimum length", async () => {
    const user = userEvent.setup();
    const onSearch = vi.fn();
    render(<SearchInput value="" onSearch={onSearch} debounceMs={20} minLength={2} />);
    const box = screen.getByRole("searchbox", { name: "Search" });
    await user.type(box, "a");
    await new Promise((r) => setTimeout(r, 40));
    expect(onSearch).not.toHaveBeenCalled();
    await user.type(box, "da");
    await waitFor(() => expect(onSearch).toHaveBeenCalledWith("ada"));
    expect(onSearch).toHaveBeenCalledTimes(1);
  });
});

describe("icon registry", () => {
  it("resolves names from data, and an unknown name renders nothing", () => {
    expect(isIconName("users")).toBe(true);
    expect(iconFor("users")).toBe(ICONS.users);
    expect(iconFor("not-an-icon")).toBeNull();
  });

  it("every registered icon exists in the installed lucide-react (a removed icon imports as undefined)", () => {
    expect(Object.entries(ICONS).filter(([, icon]) => icon === undefined)).toEqual([]);
  });
});
