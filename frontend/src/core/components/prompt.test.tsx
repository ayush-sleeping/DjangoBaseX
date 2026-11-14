import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { PromptHost, promptText } from "./prompt";

describe("promptText()", () => {
  it("rejects loudly when no host is mounted, never hangs", async () => {
    await expect(promptText({ title: "Why?", label: "Reason" })).rejects.toThrow(/PromptHost/);
  });

  it("resolves the typed value on confirm", async () => {
    const user = userEvent.setup();
    render(<PromptHost />);
    let answer: Promise<string | null>;
    act(() => {
      answer = promptText({ title: "Mark as lost", label: "Reason", confirmLabel: "Save" });
    });
    await user.type(await screen.findByLabelText("Reason"), "too expensive");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await expect(answer!).resolves.toBe("too expensive");
  });

  it("resolves null on cancel and on Escape", async () => {
    const user = userEvent.setup();
    render(<PromptHost />);
    let answer: Promise<string | null>;
    act(() => {
      answer = promptText({ title: "One", label: "Reason" });
    });
    await user.click(await screen.findByRole("button", { name: "Cancel" }));
    await expect(answer!).resolves.toBeNull();

    act(() => {
      answer = promptText({ title: "Two", label: "Reason" });
    });
    await screen.findByLabelText("Reason");
    await user.keyboard("{Escape}");
    await expect(answer!).resolves.toBeNull();
  });

  it("required keeps confirm disabled until the trimmed value is non-empty", async () => {
    const user = userEvent.setup();
    render(<PromptHost />);
    let answer: Promise<string | null>;
    act(() => {
      answer = promptText({ title: "Why?", label: "Reason", required: true });
    });
    const confirmButton = await screen.findByRole("button", { name: "Confirm" });
    expect(confirmButton).toBeDisabled();
    await user.type(screen.getByLabelText("Reason"), "   ");
    expect(confirmButton).toBeDisabled();
    await user.type(screen.getByLabelText("Reason"), "x");
    expect(confirmButton).toBeEnabled();
    await user.click(confirmButton);
    await expect(answer!).resolves.toBe("   x");
  });

  it("a newer question cancels the older one", async () => {
    render(<PromptHost />);
    let first: Promise<string | null>;
    act(() => {
      first = promptText({ title: "One", label: "A" });
      void promptText({ title: "Two", label: "B" });
    });
    await expect(first!).resolves.toBeNull();
    expect(await screen.findByText("Two")).toBeInTheDocument();
  });
});
