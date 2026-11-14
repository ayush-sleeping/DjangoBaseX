import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

let pathname = "/users";
vi.mock("next/navigation", () => ({ usePathname: () => pathname }));

import { TitleSync } from "./TitleSync";

describe("TitleSync", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    pathname = "/users";
    document.title = "";
  });
  afterEach(() => vi.useRealTimers());

  it("re-applies the template after a pathname change", () => {
    document.title = "Users";
    const { rerender } = render(<TitleSync productName="Acme" />);
    act(() => void vi.runAllTimers());
    expect(document.title).toBe("Users — Acme");

    // Navigation: Next resets the title to the bare page title; the pathname changes.
    document.title = "Roles";
    pathname = "/roles";
    rerender(<TitleSync productName="Acme" />);
    act(() => void vi.runAllTimers());
    expect(document.title).toBe("Roles — Acme");
  });

  it("never doubles the suffix and gives an empty title the product name", () => {
    document.title = "Users — Acme";
    const { rerender } = render(<TitleSync productName="Acme" />);
    expect(document.title).toBe("Users — Acme");
    document.title = "";
    pathname = "/x";
    rerender(<TitleSync productName="Acme" />);
    expect(document.title).toBe("Acme");
  });
});
