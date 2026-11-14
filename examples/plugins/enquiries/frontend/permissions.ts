/**
 * This plugin's permission codes, added to the platform's typed PermissionCode (FRONTEND_PLATFORM § 9).
 * Core's generated src/generated/permissions.ts lists core's codes only; a plugin declares its own
 * here, by module augmentation, so `can(ENQUIRY_CODES.view)` typechecks and a typo does not.
 * Keep it in step with the plugin's backend wiring.
 */
import "@/generated/permissions";

declare module "@/generated/permissions" {
  interface PermissionCodes {
    "enquiries.enquiries.view": true;
    "enquiries.enquiries.create": true;
    "enquiries.enquiries.update": true;
    "enquiries.enquiries.transition": true;
    "enquiries.enquiries.delete": true;
  }
}
