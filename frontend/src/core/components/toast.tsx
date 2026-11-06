"use client";

/**
 * toast() — one global store, callable outside React (FRONTEND_PLATFORM § 13), and one
 * <Toaster/> mounted in the root providers. The query layer's "couldn't refresh" notice arrives
 * here too, so there is one place transient messages appear.
 */
import { X } from "lucide-react";
import { useEffect, useSyncExternalStore } from "react";

import { useT } from "@/core/lib/i18n";
import { subscribeRefreshFailed } from "@/core/lib/query/refresh-failed";
import { TONE_SOLID, type Tone } from "@/core/lib/status-tone";

import { IconButton } from "./Button";

export type Toast = { id: number; message: string; tone: Tone };

let toasts: Toast[] = [];
let nextId = 1;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

/** Duration in ms; 0 keeps it until dismissed (errors default to that). */
export function toast(message: string, options: { tone?: Tone; duration?: number } = {}): number {
  const tone = options.tone ?? "neutral";
  const id = nextId++;
  toasts = [...toasts, { id, message, tone }];
  emit();
  const duration = options.duration ?? (tone === "err" ? 0 : 5000);
  if (duration > 0) setTimeout(() => dismissToast(id), duration);
  return id;
}

export function dismissToast(id: number): void {
  toasts = toasts.filter((t) => t.id !== id);
  emit();
}

/** Tests only. */
export function resetToasts(): void {
  toasts = [];
  emit();
}

const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};
const EMPTY: Toast[] = [];

export function Toaster() {
  const copy = useT("components.toast");
  const items = useSyncExternalStore(subscribe, () => toasts, () => EMPTY);
  useEffect(() => subscribeRefreshFailed((event) => void toast(event.message, { tone: "warn" })), []);
  return (
    <div aria-live="polite" className="pointer-events-none fixed bottom-4 end-4 z-50 flex w-full max-w-sm flex-col gap-2">
      {items.map((t) => (
        <div key={t.id} role={t.tone === "err" ? "alert" : "status"} className={`pointer-events-auto flex items-start gap-2 rounded-md px-3 py-2 text-sm shadow-md ${TONE_SOLID[t.tone]}`}>
          <p className="min-w-0 flex-1">{t.message}</p>
          <IconButton icon={X} label={copy("dismiss")} variant="link" className="text-inherit" onClick={() => dismissToast(t.id)} />
        </div>
      ))}
    </div>
  );
}
