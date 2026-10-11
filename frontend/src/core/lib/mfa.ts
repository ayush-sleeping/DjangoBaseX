/**
 * Two-factor setup and removal for the signed-in user (AUTH_BLUEPRINT § 6.8, § 6.9).
 *
 * Recovery codes are returned once, by confirmMfaSetup(), and live only in component state until
 * the user leaves the page. Never write them to storage, a cookie or a log.
 */
import { api, ApiError, isReauthRequired } from "./api";
import { confirmPassword } from "./auth";

/** Where to send a user on `mfa_enrollment_required` (isMfaEnrollmentRequired in ./api). */
export const MFA_ENROLMENT_PATH = "/account/security";

export type MfaSetup = { otpauth_uri: string; secret: string };

/** Creates a fresh unconfirmed device, replacing any earlier unconfirmed one. */
export async function startMfaSetup(): Promise<MfaSetup> {
  return api<MfaSetup>("/api/auth/mfa/setup/", { method: "POST", body: "{}" });
}

/** The first code from the authenticator app turns the device on. Returns the recovery codes. */
export async function confirmMfaSetup(code: string): Promise<string[]> {
  const body = await api<{ recovery_codes: string[] }>("/api/auth/mfa/confirm/", {
    method: "POST",
    body: JSON.stringify({ code }),
  });
  return body.recovery_codes;
}

/** Throws an ApiError the caller can test with isReauthRequired() when the password is needed. */
export async function disableMfa(): Promise<void> {
  await api<void>("/api/auth/mfa/disable/", { method: "POST", body: "{}" });
}

/** The re-auth path: confirm the password, then retry the removal exactly once. */
export async function confirmPasswordAndDisableMfa(password: string): Promise<void> {
  await confirmPassword(password);
  await disableMfa();
}

/** "JBSWY3DPEHPK3PXP" → "JBSW Y3DP EHPK 3PXP": easier to type into an authenticator by hand. */
export function formatSecret(secret: string): string {
  return secret.replace(/\s+/g, "").match(/.{1,4}/g)?.join(" ") ?? "";
}

/** The recovery codes as one block of text, for the copy-all button. */
export function recoveryCodesText(codes: string[]): string {
  return codes.join("\n");
}

export function mfaErrorMessage(error: unknown): string {
  if (isReauthRequired(error)) {
    return "Your password could not be confirmed for this action. Try again.";
  }
  if (error instanceof ApiError) {
    switch (error.code) {
      case "invalid_mfa_code":
        return "That code is not valid. Check the time on your device and try again.";
      case "invalid_credentials":
        return "That password is not correct.";
      case "mfa_already_enabled":
        return "Two-factor is already on for this account.";
    }
    if (error.status === 401) return "Your session has ended. Sign in again.";
    if (error.status === 429) return "Too many attempts. Wait a minute and try again.";
  }
  return "Could not reach the server. Try again.";
}
