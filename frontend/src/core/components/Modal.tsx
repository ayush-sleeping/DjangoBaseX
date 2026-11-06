"use client";

/**
 * The one modal shape (FRONTEND_PLATFORM § 13): header → scrolling body → fixed footer, messages
 * left and actions right. A form's submit button sits in the footer with `form="<id>"`.
 *
 * Built on Headless UI's Dialog: focus trap, Escape, scroll lock, inert background and the
 * aria-modal wiring come from one audited implementation, never a hand-rolled overlay.
 */
import { Dialog, DialogPanel, DialogTitle } from "@headlessui/react";
import { X } from "lucide-react";
import type { ReactNode } from "react";

import { IconButton } from "./Button";

export type ModalSize = "sm" | "md" | "lg" | "xl";
const WIDTH: Record<ModalSize, string> = { sm: "max-w-sm", md: "max-w-lg", lg: "max-w-2xl", xl: "max-w-4xl" };

export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  footerMessage,
  size = "md",
  dismissible = true,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  /** Actions, right-aligned. */
  footer?: ReactNode;
  /** An error or hint, left of the actions. */
  footerMessage?: ReactNode;
  size?: ModalSize;
  /** False while a submit is in flight: Escape and the backdrop do nothing. */
  dismissible?: boolean;
}) {
  return (
    <Dialog open={open} onClose={() => dismissible && onClose()} className="relative z-50">
      <div aria-hidden className="fixed inset-0 bg-foreground/40" />
      <div className="fixed inset-0 flex items-center justify-center p-4">
        <DialogPanel
          className={`flex max-h-[90dvh] w-full ${WIDTH[size]} flex-col rounded-xl border border-border bg-popover text-popover-foreground shadow-lg`}
        >
          <header className="flex items-center justify-between gap-4 border-b border-border px-5 py-3">
            <DialogTitle className="text-base font-semibold">{title}</DialogTitle>
            <IconButton icon={X} label="Close" onClick={onClose} disabled={!dismissible} />
          </header>
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
          {footer || footerMessage ? (
            <footer className="flex items-center justify-between gap-4 border-t border-border px-5 py-3">
              <div className="min-w-0 text-sm">{footerMessage}</div>
              <div className="flex shrink-0 gap-2">{footer}</div>
            </footer>
          ) : null}
        </DialogPanel>
      </div>
    </Dialog>
  );
}
