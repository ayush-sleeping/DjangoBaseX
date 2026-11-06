/**
 * Status tones (FRONTEND_PLATFORM § 13, § 16). The ONE place a status becomes colour.
 *
 * Recipes are LITERAL class strings: Tailwind emits only class names it finds whole in source, so
 * `bg-${tone}-tint` would compile to nothing and render a transparent chip with no error.
 *
 * Which tone a status HAS is backend data (registry.statuses → src/generated/statuses.ts and
 * bootstrap's `statuses`), read through useStatus() in ./statuses.tsx. This file only says what each
 * tone LOOKS like.
 */
import type { Tone } from "@/generated/statuses";

export type { StatusMeta, Tone } from "@/generated/statuses";

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
