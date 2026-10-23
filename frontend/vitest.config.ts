// Frontend tests (FRONTEND_PLATFORM.md § 26): non-watch by default, timezone pinned, jsdom,
// process isolation. Guard tests live in tests/architecture/; unit tests sit next to their module.
import path from "node:path";

import { defineConfig } from "vitest/config";

process.env.TZ = "UTC";

export default defineConfig({
  esbuild: { jsx: "automatic" },
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  test: {
    environment: "jsdom",
    globals: false,
    pool: "forks",
    isolate: true,
    setupFiles: ["./tests/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}", "tests/**/*.test.{ts,tsx}"],
    exclude: ["node_modules", ".next", "tests/fixtures/**"],
    env: { TZ: "UTC" },
  },
});
