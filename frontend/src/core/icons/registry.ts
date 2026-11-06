/**
 * Icons by NAME (FRONTEND_PLATFORM § 10, BUILD_ORDER 8.3a). The backend and the nav manifest name an
 * icon ("users"); the client owns the SVG, so a restyle is never a backend deploy. Every icon a
 * module may name is listed here once; core code imports lucide-react directly only for its own
 * fixed chrome (close, chevrons).
 */
import {
  Bell,
  Check,
  Cog,
  FileText,
  Folder,
  Home,
  KeyRound,
  LayoutDashboard,
  Lock,
  LogOut,
  type LucideIcon,
  Mail,
  Pencil,
  Plus,
  Search,
  Shield,
  ShieldCheck,
  Trash2,
  UserPlus,
  Users,
} from "lucide-react";

export const ICONS = {
  bell: Bell,
  check: Check,
  dashboard: LayoutDashboard,
  delete: Trash2,
  edit: Pencil,
  file: FileText,
  folder: Folder,
  home: Home,
  invite: UserPlus,
  key: KeyRound,
  lock: Lock,
  "log-out": LogOut,
  mail: Mail,
  plus: Plus,
  roles: Shield,
  search: Search,
  security: ShieldCheck,
  settings: Cog,
  users: Users,
} as const satisfies Record<string, LucideIcon>;

export type IconName = keyof typeof ICONS;

export function isIconName(name: unknown): name is IconName {
  return typeof name === "string" && Object.hasOwn(ICONS, name);
}

/** The icon for a name from data, or null — an unknown name renders nothing, never a crash. */
export function iconFor(name: string | null | undefined): LucideIcon | null {
  return isIconName(name) ? ICONS[name] : null;
}
