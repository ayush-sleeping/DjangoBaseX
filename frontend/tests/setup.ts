// Every test: jest-dom matchers, and the network mocked at the network (MSW), never at the
// module, so the transport's real logic (refresh, error decoding, headers) runs in each test.
import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { setupServer } from "msw/node";
import { type ComponentType, createElement, type ReactNode } from "react";
import { afterAll, afterEach, beforeAll, vi } from "vitest";

import { resetWarnings } from "@/core/lib/i18n/messages";

export const server = setupServer();

// Every render and renderHook runs inside the source catalogue (tests/i18n.tsx), around any wrapper
// the test passes, so components that translate render in a test exactly as in the app. This wraps
// the harness; it mocks no application module.
vi.mock("@testing-library/react", async (importOriginal) => {
  const rtl = await importOriginal<typeof import("@testing-library/react")>();
  const { SourceIntl } = await import("./i18n");
  type Wrapper = ComponentType<{ children: ReactNode }> | undefined;
  const wrap = (inner: Wrapper) =>
    function I18nWrapper({ children }: { children: ReactNode }) {
      return createElement(SourceIntl, null, inner ? createElement(inner, null, children) : children);
    };
  return {
    ...rtl,
    render: ((ui: Parameters<typeof rtl.render>[0], options?: Parameters<typeof rtl.render>[1]) =>
      rtl.render(ui, { ...options, wrapper: wrap(options?.wrapper as Wrapper) })) as typeof rtl.render,
    renderHook: ((callback: (props: unknown) => unknown, options?: Parameters<typeof rtl.renderHook>[1]) =>
      rtl.renderHook(callback, { ...options, wrapper: wrap(options?.wrapper as Wrapper) })) as typeof rtl.renderHook,
  };
});

// jsdom has no ResizeObserver; Headless UI's anchored popovers (Select, Modal) observe their size.
// A no-op stub is enough: tests assert behaviour, not layout.
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  resetWarnings(); // the i18n development warnings are once-per-text: start each test fresh
  server.resetHandlers();
  cleanup();
});
afterAll(() => server.close());
