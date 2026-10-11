/**
 * Roles and their grants (AUTH_BLUEPRINT Ch. 8, § 10.3; BUILD_ORDER 1.4). Pages call these and the
 * message helpers; they never shape a request or read an error body themselves.
 */
import { api, ApiError } from "./api";

/** The code each endpoint enforces. Gate every control on exactly one of these (affordance parity). */
export const ROLE_CODES = {
  /** GET /api/rbac/permissions/: the catalog the grants editor shows. */
  viewCatalog: "rbac.permissions.view",
  /** GET roles, GET a role, GET a user's roles. */
  view: "rbac.roles.view",
  /** POST /api/rbac/roles/. */
  create: "rbac.roles.create",
  /** PATCH a role, and PUT its grants. */
  update: "rbac.roles.update",
  /** DELETE a role. */
  delete: "rbac.roles.delete",
  /** POST and DELETE a user's role. */
  assign: "rbac.roles.assign",
} as const;

export type CatalogPermission = { code: string; label: string; is_deprecated: boolean };

export type PermissionGroup = {
  code: string;
  label: string;
  module: string;
  order: number;
  permissions: CatalogPermission[];
};

export type Role = {
  public_id: string;
  name: string;
  slug: string;
  description: string;
  is_system: boolean;
  is_elevated: boolean;
  mfa_required: boolean;
  /** Granted codes, sorted. */
  permissions: string[];
  user_count: number;
  created_at: string;
  updated_at: string;
};

export type Page<T> = { count: number; next: string | null; previous: string | null; results: T[] };

export type NewRole = {
  name: string;
  slug: string;
  description?: string;
  is_elevated?: boolean;
  mfa_required?: boolean;
  permissions?: string[];
};

/** The slug is fixed at creation: PATCH accepts none. */
export type RoleChanges = Partial<Pick<Role, "name" | "description" | "is_elevated" | "mfa_required">>;

const ROLES = "/api/rbac/roles/";
const roleUrl = (publicId: string) => `${ROLES}${encodeURIComponent(publicId)}/`;

export async function listPermissionGroups(): Promise<PermissionGroup[]> {
  return api<PermissionGroup[]>("/api/rbac/permissions/", { cache: "no-store" });
}

export async function listRoles(page = 1): Promise<Page<Role>> {
  return api<Page<Role>>(`${ROLES}?page=${page}`, { cache: "no-store" });
}

export async function getRole(publicId: string): Promise<Role> {
  return api<Role>(roleUrl(publicId), { cache: "no-store" });
}

export async function createRole(role: NewRole): Promise<Role> {
  return api<Role>(ROLES, { method: "POST", body: JSON.stringify(role) });
}

export async function updateRole(publicId: string, changes: RoleChanges): Promise<Role> {
  return api<Role>(roleUrl(publicId), { method: "PATCH", body: JSON.stringify(changes) });
}

export async function deleteRole(publicId: string): Promise<void> {
  await api<void>(roleUrl(publicId), { method: "DELETE" });
}

/** FULL replacement: the role ends up holding exactly `codes`. */
export async function replaceRolePermissions(
  publicId: string,
  codes: string[],
): Promise<{ added: string[]; removed: string[] }> {
  return api(`${roleUrl(publicId)}permissions/`, {
    method: "PUT",
    body: JSON.stringify({ permissions: [...new Set(codes)].sort() }),
  });
}

// Role assignment. No screen calls these yet: the users list arrives with BUILD_ORDER 1.5.
const userRolesUrl = (userPublicId: string) =>
  `/api/rbac/users/${encodeURIComponent(userPublicId)}/roles/`;

export async function listUserRoles(userPublicId: string): Promise<Role[]> {
  return api<Role[]>(userRolesUrl(userPublicId), { cache: "no-store" });
}

export async function assignRole(userPublicId: string, rolePublicId: string): Promise<Role> {
  return api<Role>(userRolesUrl(userPublicId), {
    method: "POST",
    body: JSON.stringify({ role: rolePublicId }),
  });
}

export async function unassignRole(userPublicId: string, rolePublicId: string): Promise<void> {
  await api<void>(`${userRolesUrl(userPublicId)}${encodeURIComponent(rolePublicId)}/`, {
    method: "DELETE",
  });
}

/** "Support Agents" → "support-agents": a starting point the user can edit before creating. */
export function suggestSlug(name: string): string {
  return name
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 50);
}

/** How many of a group's permissions are in `granted`: the grants editor's per-group count. */
export function grantedIn(group: PermissionGroup, granted: ReadonlySet<string>): number {
  return group.permissions.filter((p) => granted.has(p.code)).length;
}

/** Field → messages, from a 400 `invalid`. Empty when the error is anything else. */
export function fieldErrors(error: unknown): Record<string, string[]> {
  if (!(error instanceof ApiError) || error.status !== 400 || error.code !== "invalid") return {};
  const details = error.details;
  if (!details || typeof details !== "object" || Array.isArray(details)) return {};
  const out: Record<string, string[]> = {};
  for (const [field, messages] of Object.entries(details)) {
    const list = Array.isArray(messages) ? messages : [messages];
    out[field] = list.filter((m): m is string => typeof m === "string");
  }
  return out;
}

/** One message safe to show, for every RBAC failure. Handles both error shapes (see below). */
export function rbacErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return "Could not reach the server. Try again.";
  switch (error.code) {
    case "system_role":
      return "System roles cannot be renamed, deleted, or have their permissions changed.";
    case "elevated_requires_superuser":
      return "Only a superuser can create, change or assign an elevated role.";
    case "role_in_use": {
      const count = (error.details as { user_count?: unknown } | undefined)?.user_count;
      const who = typeof count === "number" ? `${count} user${count === 1 ? "" : "s"}` : "Users";
      return `${who} still hold this role. Remove it from them before deleting it.`;
    }
    case "unknown_permission": {
      const codes = Array.isArray(error.details) ? error.details.join(", ") : "";
      return `These permissions do not exist: ${codes || "(unknown)"}. Reload and try again.`;
    }
    case "last_administrator":
      return "This is the last administrator. Give the role to someone else first.";
    case "invalid":
      return "Check the highlighted fields.";
    case "mfa_enrollment_required":
      return "Your role requires two-factor authentication. Set it up first.";
  }
  // DRF's own denials have no envelope, only {"detail": "..."}; the status says enough.
  if (error.status === 403) return "You don't have permission to do that.";
  if (error.status === 404) return "That role does not exist, or you cannot see it.";
  if (error.status === 401) return "Your session has ended. Sign in again.";
  if (error.status === 429) return "Too many requests. Wait a minute and try again.";
  return "Something went wrong. Try again.";
}
