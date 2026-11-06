/**
 * Status tones (FRONTEND_PLATFORM § 13, § 16). The ONE place a status becomes colour.
 *
 * Recipes are LITERAL class strings: Tailwind emits only class names it finds whole in source, so
 * `bg-${tone}-tint` would compile to nothing and render a transparent chip with no error.
 *
 * STATUSES is local until BUILD_ORDER 8.4 exports the backend's per-choice status metadata; then a
 * plugin declares the tone of its own statuses and this table becomes that export.
 */
export type Tone = "ok" | "warn" | "err" | "info" | "neutral";

export const TONE_PILL: Record<Tone, string> = {
  ok: "bg-ok-tint text-ok-text ring-ok-dot/30",
  warn: "bg-warn-tint text-warn-text ring-warn-dot/30",
  err: "bg-err-tint text-err-text ring-err-dot/30",
  info: "bg-info-tint text-info-text ring-info-dot/30",
  neutral: "bg-neutral-tint text-neutral-text ring-neutral-dot/30",
};

export const TONE_DOT: Record<Tone, string> = {
  ok: "bg-ok-dot",
  warn: "bg-warn-dot",
  err: "bg-err-dot",
  info: "bg-info-dot",
  neutral: "bg-neutral-dot",
};

export const TONE_SOLID: Record<Tone, string> = {
  ok: "bg-ok-solid text-ok-solid-foreground",
  warn: "bg-warn-solid text-warn-solid-foreground",
  err: "bg-err-solid text-err-solid-foreground",
  info: "bg-info-solid text-info-solid-foreground",
  neutral: "bg-neutral-solid text-neutral-solid-foreground",
};

/** Not set: dashed, no hue — distinct from any real status. */
export const TONE_EMPTY = "border border-dashed border-border text-muted-foreground";

export type StatusMeta = { tone: Tone; label: string; transitional?: boolean };

/** status key → how it looks. A decision such as "suspended is warn, not err" is made here once. */
export const STATUSES: Record<string, StatusMeta> = {
  "user.active": { tone: "ok", label: "Active" },
  "user.deactivated": { tone: "err", label: "Deactivated" },
  "user.superuser": { tone: "warn", label: "Superuser" },
  "user.mfa_on": { tone: "info", label: "Two-factor on" },
  "invitation.pending": { tone: "info", label: "Pending", transitional: true },
  "invitation.accepted": { tone: "ok", label: "Accepted" },
  "invitation.revoked": { tone: "neutral", label: "Revoked" },
  "invitation.expired": { tone: "warn", label: "Expired" },
  "role.system": { tone: "neutral", label: "System" },
  "role.elevated": { tone: "warn", label: "Elevated" },
  "role.mfa_required": { tone: "info", label: "Two-factor required" },
};
