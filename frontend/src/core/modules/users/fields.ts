/**
 * Form schemas (FRONTEND_PLATFORM § 15). A courtesy check before the request: the API is the
 * validator, and its field errors land on the same fields through applyServerErrors.
 */
import { z } from "zod";

export const userCreateSchema = z.object({
  email: z.email({ error: "Enter a valid email address." }),
  full_name: z.string().trim().max(150, { error: "Use 150 characters or fewer." }),
});
export type UserCreateValues = z.infer<typeof userCreateSchema>;

export const userEditSchema = z.object({
  full_name: z.string().trim().max(150, { error: "Use 150 characters or fewer." }),
});
export type UserEditValues = z.infer<typeof userEditSchema>;

export const deactivateSchema = z.object({
  reason: z.string().trim().max(255, { error: "Use 255 characters or fewer." }),
});
export type DeactivateValues = z.infer<typeof deactivateSchema>;

export const invitationSchema = z.object({
  email: z.email({ error: "Enter a valid email address." }),
  role: z.string().min(1, { error: "Choose a role." }),
});
export type InvitationValues = z.infer<typeof invitationSchema>;
