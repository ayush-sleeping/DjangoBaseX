// Every test: jest-dom matchers, and the network mocked at the network (MSW), never at the
// module, so the transport's real logic (refresh, error decoding, headers) runs in each test.
import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll } from "vitest";

export const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  cleanup();
});
afterAll(() => server.close());
