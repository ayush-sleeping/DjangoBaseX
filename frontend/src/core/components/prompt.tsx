"use client";

/**
 * promptText() — imperative text input, the sibling of confirm() (FRONTEND_PLATFORM § 13), backed by ONE
 * root-mounted <PromptHost/>. window.prompt is banned by the lint rule; this is its replacement, named promptText so the
 * rule (which matches a bare `prompt(`) still catches the browser global.
 *
 *   const reason = await promptText({ title: "Mark as lost", label: "Reason", required: true });
 *   if (reason !== null) …   // null = cancelled (button, Escape, backdrop)
 *
 * Same contract as confirm(): no host mounted → rejects loudly instead of hanging; a newer question
 * cancels the older one.
 */
import { useId, useState, useSyncExternalStore } from "react";

import { useT } from "@/core/lib/i18n";

import { Button } from "./Button";
import { inputClass } from "./form/styles";
import { Modal } from "./Modal";

export type PromptOptions = {
  title: string;
  label: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /** The confirm button stays disabled until the trimmed value is non-empty. */
  required?: boolean;
};

type Pending = PromptOptions & { id: number; resolve: (value: string | null) => void };

let current: Pending | null = null;
let hosts = 0;
let asked = 0;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

export function promptText(options: PromptOptions): Promise<string | null> {
  if (hosts === 0) return Promise.reject(new Error("promptText() needs <PromptHost/> mounted in the root providers"));
  current?.resolve(null); // one question at a time: a newer one cancels the older
  return new Promise<string | null>((resolve) => {
    asked += 1;
    current = { ...options, id: asked, resolve };
    emit();
  });
}

function settle(value: string | null) {
  const pending = current;
  current = null;
  emit();
  pending?.resolve(value);
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  hosts += 1;
  return () => {
    listeners.delete(listener);
    hosts -= 1;
    if (hosts === 0 && current) settle(null);
  };
}

function PromptBody({ pending }: { pending: Pending }) {
  const t = useT();
  const formId = useId();
  const [value, setValue] = useState("");
  const blocked = pending.required === true && value.trim() === "";
  return (
    <Modal
      open
      onClose={() => settle(null)}
      title={pending.title}
      size="sm"
      footer={
        <>
          <Button variant="secondary" onClick={() => settle(null)}>
            {pending.cancelLabel ?? t("common.cancel")}
          </Button>
          <Button type="submit" form={formId} disabled={blocked}>
            {pending.confirmLabel ?? t("components.confirm.confirm")}
          </Button>
        </>
      }
    >
      <form
        id={formId}
        onSubmit={(event) => {
          event.preventDefault();
          if (!blocked) settle(value);
        }}
      >
        <label className="mb-1 block text-sm font-medium" htmlFor={`${formId}-input`}>
          {pending.label}
        </label>
        <input
          id={`${formId}-input`}
          className={inputClass}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          required={pending.required}
          autoFocus
        />
      </form>
    </Modal>
  );
}

export function PromptHost() {
  const pending = useSyncExternalStore(subscribe, () => current, () => null);
  // Keyed per question, so each one (even a repeat of the same text) starts with an empty field.
  return pending ? <PromptBody key={pending.id} pending={pending} /> : null;
}
