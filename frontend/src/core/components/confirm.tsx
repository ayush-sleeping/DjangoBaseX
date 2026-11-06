"use client";

/**
 * confirm() — imperative, backed by ONE root-mounted <ConfirmHost/> (FRONTEND_PLATFORM § 13).
 *
 *   if (await confirm({ title: "Deactivate Ada?", tone: "danger", confirmLabel: "Deactivate" })) …
 *
 * There is no hook to half-use: a hook whose promise only a separately rendered Dialog could settle
 * once left a "Void" button doing nothing, forever, because one caller forgot the Dialog. Here the
 * host is mounted once in the root providers (tests/architecture/confirm-host.test.tsx), and a
 * confirm() with no host mounted rejects loudly instead of hanging.
 */
import { type ReactNode, useSyncExternalStore } from "react";

import { useT } from "@/core/lib/i18n";

import { Button } from "./Button";
import { Modal } from "./Modal";

export type ConfirmOptions = {
  title: string;
  body?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: "default" | "danger";
};

type Pending = ConfirmOptions & { resolve: (ok: boolean) => void };

let current: Pending | null = null;
let hosts = 0;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

export function confirm(options: ConfirmOptions): Promise<boolean> {
  if (hosts === 0) return Promise.reject(new Error("confirm() needs <ConfirmHost/> mounted in the root providers"));
  current?.resolve(false); // one question at a time: a newer one cancels the older
  return new Promise<boolean>((resolve) => {
    current = { ...options, resolve };
    emit();
  });
}

function settle(ok: boolean) {
  const pending = current;
  current = null;
  emit();
  pending?.resolve(ok);
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  hosts += 1;
  return () => {
    listeners.delete(listener);
    hosts -= 1;
    if (hosts === 0 && current) settle(false);
  };
}

export function ConfirmHost() {
  const t = useT();
  const pending = useSyncExternalStore(subscribe, () => current, () => null);
  return (
    <Modal
      open={pending !== null}
      onClose={() => settle(false)}
      title={pending?.title ?? ""}
      size="sm"
      footer={
        <>
          <Button variant="secondary" onClick={() => settle(false)}>
            {pending?.cancelLabel ?? t("common.cancel")}
          </Button>
          <Button variant={pending?.tone === "danger" ? "destructive" : "primary"} onClick={() => settle(true)} autoFocus>
            {pending?.confirmLabel ?? t("components.confirm.confirm")}
          </Button>
        </>
      }
    >
      {pending?.body ? <div className="text-sm text-muted-foreground">{pending.body}</div> : null}
    </Modal>
  );
}
