import { RouteGate } from "@/core/shell/nav/route-gate";

/**
 * Plugin pages pass the same route gate as core's (FRONTEND_PLATFORM § 10): a plugin page needs a
 * navigation entry the user's bootstrap carries, or it is refused.
 */
export default function PluginsLayout({ children }: LayoutProps<"/">) {
  return <RouteGate>{children}</RouteGate>;
}
