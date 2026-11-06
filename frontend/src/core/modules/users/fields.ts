/**
 * Form schemas (FRONTEND_PLATFORM § 15). A courtesy check before the request: the API is the
 * validator, and its field errors land on the same fields through applyServerErrors.
 *
 * Each schema is built from the viewer's translated copy (useValidationCopy), so its messages are in
 * the viewer's language: a schema at module scope could only hold one language's literals.
 */
import { useMemo } from "react";
import { z } from "zod";

import { useT } from "@/core/lib/i18n";

export type ValidationCopy = { email: string; chooseRole: string; tooLong: (max: number) => string };

export function useValidationCopy(): ValidationCopy {
  const t = useT("users.validation");
  return useMemo(() => ({ email: t("email"), chooseRole: t("chooseRole"), tooLong: (max: number) => t("tooLong", { max }) }), [t]);
}

const name = (copy: ValidationCopy) => z.string().trim().max(150, { error: copy.tooLong(150) });

export const userCreateSchema = (copy: ValidationCopy) => z.object({ email: z.email({ error: copy.email }), full_name: name(copy) });
export type UserCreateValues = z.infer<ReturnType<typeof userCreateSchema>>;

export const userEditSchema = (copy: ValidationCopy) => z.object({ full_name: name(copy) });
export type UserEditValues = z.infer<ReturnType<typeof userEditSchema>>;

export const deactivateSchema = (copy: ValidationCopy) => z.object({ reason: z.string().trim().max(255, { error: copy.tooLong(255) }) });
export type DeactivateValues = z.infer<ReturnType<typeof deactivateSchema>>;

export const invitationSchema = (copy: ValidationCopy) =>
  z.object({ email: z.email({ error: copy.email }), role: z.string().min(1, { error: copy.chooseRole }) });
export type InvitationValues = z.infer<ReturnType<typeof invitationSchema>>;
