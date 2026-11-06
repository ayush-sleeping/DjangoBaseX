"use client";

/**
 * A role that requires two-factor makes every endpoint but enrolment answer
 * 403 mfa_enrollment_required. The shells send the user to enrolment instead of showing a list or
 * record error — one place, so no module forgets it (FRONTEND_PLATFORM § 7, mandatory prompts).
 */
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { isMfaEnrollmentRequired } from "@/core/lib/api";
import { MFA_ENROLMENT_PATH } from "@/core/lib/mfa";

export function useEnrolmentRedirect(error: unknown): void {
  const router = useRouter();
  const required = isMfaEnrollmentRequired(error);
  useEffect(() => {
    if (required) router.push(MFA_ENROLMENT_PATH);
  }, [required, router]);
}
