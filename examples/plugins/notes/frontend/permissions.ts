/**
 * This plugin's permission codes, added to the platform's typed PermissionCode (FRONTEND_PLATFORM § 9).
 * Core's generated src/generated/permissions.ts lists core's codes only; a plugin declares its own
 * here, by module augmentation, so `can(NOTE_CODES.view)` typechecks and a typo does not.
 * Keep it in step with djx_notes/wiring.py.
 */
import "@/generated/permissions";

declare module "@/generated/permissions" {
  interface PermissionCodes {
    "notes.notes.view": true;
    "notes.notes.create": true;
    "notes.notes.delete": true;
  }
}
