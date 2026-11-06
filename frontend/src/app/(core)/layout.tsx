import { RouteGate } from "@/core/shell/nav/route-gate";

/**
 * The core portal's layout (FRONTEND_PLATFORM § 10): every page below renders through the route
 * gate, so a page with no navigation entry is refused rather than reachable by URL.
 */
export default function CoreLayout({ children }: LayoutProps<"/">) {
  return <RouteGate>{children}</RouteGate>;
}
