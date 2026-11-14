import path from "node:path";

import type { NextConfig } from "next";

import { securityHeaders } from "./src/core/lib/security/headers";

const nextConfig: NextConfig = {
  // Static security headers (FRONTEND_PLATFORM § 18, BUILD_ORDER 8.5b); the CSP is per request in
  // src/proxy.ts. Here they apply whichever layer serves the response.
  poweredByHeader: false,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: securityHeaders({ isProduction: process.env.NODE_ENV === "production" }),
      },
    ];
  },
  // A plugin's frontend half is symlinked in from backend/plugins/<name>/frontend
  // (CORE_ARCHITECTURE_PLAN § 5, BUILD_ORDER 3.5). Turbopack resolves nothing outside its root,
  // so the root is the repository, the common parent of both (TECH_DEBT DB-28).
  turbopack: {
    root: path.resolve(__dirname, ".."),
  },
};

export default nextConfig;
