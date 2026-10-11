import path from "node:path";

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // A plugin's frontend half is symlinked in from backend/plugins/<name>/frontend
  // (CORE_ARCHITECTURE_PLAN § 5, BUILD_ORDER 3.5). Turbopack resolves nothing outside its root,
  // so the root is the repository, the common parent of both (TECH_DEBT DB-28).
  turbopack: {
    root: path.resolve(__dirname, ".."),
  },
};

export default nextConfig;
