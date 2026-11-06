/** Query keys for the Users module (FRONTEND_PLATFORM § 4). Mutations invalidate by root. */
import { defineKeys } from "@/core/lib/query/keys";

export const userKeys = defineKeys("users", {
  list: (query: { page: number; search: string }) => ["list", query],
  detail: (publicId: string) => ["detail", publicId],
});

export const invitationKeys = defineKeys("users.invitations", {
  list: (query: { page: number }) => ["list", query],
});
