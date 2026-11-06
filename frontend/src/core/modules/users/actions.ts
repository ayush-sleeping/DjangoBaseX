/**
 * Every action the Users module offers, with the ONE permission its endpoint enforces (affordance
 * parity, FRONTEND_PLATFORM § 9). A control is gated on exactly this code — never a broader flag.
 */
import { INVITATION_CODES } from "@/core/lib/invitations";
import { ROLE_CODES } from "@/core/lib/rbac";
import { USER_CODES } from "@/core/lib/users";

export const USER_ACTIONS = {
  view: { permission: USER_CODES.view, endpoint: "GET /api/users/{id}/" },
  create: { permission: USER_CODES.create, endpoint: "POST /api/users/" },
  edit: { permission: USER_CODES.update, endpoint: "PATCH /api/users/{id}/" },
  deactivate: { permission: USER_CODES.deactivate, endpoint: "POST /api/users/{id}/deactivate/" },
  activate: { permission: USER_CODES.deactivate, endpoint: "POST /api/users/{id}/activate/" },
  revokeSessions: { permission: USER_CODES.revokeSessions, endpoint: "POST /api/users/{id}/sessions/revoke/" },
  assignRole: { permission: ROLE_CODES.assign, endpoint: "POST /api/rbac/users/{id}/roles/" },
  invite: { permission: INVITATION_CODES.send, endpoint: "POST /api/users/invitations/" },
  revokeInvitation: { permission: INVITATION_CODES.send, endpoint: "POST /api/users/invitations/{id}/revoke/" },
} as const;

export type UserAction = keyof typeof USER_ACTIONS;
