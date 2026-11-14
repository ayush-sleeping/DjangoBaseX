"use client";

// Client component: enquiries are authenticated data, and the session is an httpOnly cookie.
import Link from "next/link";
import { type FormEvent, useCallback, useEffect, useState } from "react";

import { promptText } from "@/core/components/prompt";
import { fieldErrors, isApiError } from "@/core/lib/api";
import { useT } from "@/core/lib/i18n";
import { usePermissions } from "@/core/lib/permissions";

import {
  createEnquiry,
  deleteEnquiry,
  ENQUIRY_CODES,
  type Enquiry,
  type EnquiryTransition,
  listEnquiries,
  transitionEnquiry,
} from "./enquiries";

const ui = {
  card: "w-full max-w-3xl space-y-3 rounded-xl border border-border p-6",
  input: "w-full rounded-md border border-input px-3 py-2",
  button:
    "rounded-md bg-primary px-3 py-2 text-sm text-primary-foreground disabled:opacity-50",
};

function contactLine(enquiry: Enquiry): string {
  return `${enquiry.contact_name} (${enquiry.contact_email})`;
}

export default function EnquiriesPage() {
  // This plugin's own namespace (its name), from messages/*.json via the (plugins) layout.
  const t = useT("enquiries");
  const perms = usePermissions();
  const [enquiries, setEnquiries] = useState<Enquiry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const canView = perms.can(ENQUIRY_CODES.view);

  const load = useCallback(() => {
    listEnquiries()
      .then((page) => setEnquiries(page.results))
      .catch(() => setError(t("loadFailed")));
  }, [t]);

  useEffect(() => {
    if (canView) load();
  }, [canView, load]);

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const field = (name: string) => String(data.get(name) ?? "");
    try {
      await createEnquiry({
        contact_name: field("contact_name"),
        contact_email: field("contact_email"),
        subject: field("subject"),
        message: field("message"),
        value_amount: field("value_amount"),
        value_currency: field("value_currency"),
      });
      form.reset();
      setError(null);
      load();
    } catch (caught) {
      const errors = fieldErrors(caught);
      setError(Object.values(errors)[0]?.[0] ?? t("saveFailed"));
    }
  }

  async function sendTransition(enquiry: Enquiry, to: string, reason?: string) {
    try {
      await transitionEnquiry(enquiry.public_id, to, reason);
      setError(null);
      load();
    } catch (caught) {
      setError((isApiError(caught) && caught.serverMessage) || t("transitionFailed"));
    }
  }

  async function handleTransition(enquiry: Enquiry, transition: EnquiryTransition) {
    // The server says which moves need a reason (needs_reason); the page never re-derives that rule.
    if (!transition.needs_reason) return sendTransition(enquiry, transition.to);
    const reason = await promptText({
      title: t("moveTo", { status: transition.to }),
      label: t("reasonPrompt"),
      required: true,
    });
    if (reason !== null) await sendTransition(enquiry, transition.to, reason);
  }

  async function handleDelete(enquiry: Enquiry) {
    try {
      await deleteEnquiry(enquiry.public_id);
      load();
    } catch {
      setError(t("deleteFailed"));
    }
  }

  let content;
  if (perms.status === "loading") content = <p className="text-sm text-muted-foreground">{t("checking")}</p>;
  else if (!perms.user)
    content = (
      <Link className="text-sm underline" href="/login">
        {t("signIn")}
      </Link>
    );
  else if (!canView) content = <p className="text-sm">{t("denied")}</p>;
  else
    content = (
      <>
        {perms.can(ENQUIRY_CODES.create) && (
          <form onSubmit={handleCreate} className={ui.card}>
            <input name="contact_name" placeholder={t("contactName")} aria-label={t("contactName")} className={ui.input} />
            <input
              name="contact_email"
              type="email"
              placeholder={t("contactEmail")}
              aria-label={t("contactEmail")}
              className={ui.input}
            />
            <input name="subject" placeholder={t("subject")} aria-label={t("subject")} className={ui.input} />
            <textarea name="message" placeholder={t("message")} aria-label={t("message")} className={ui.input} />
            <input
              name="value_amount"
              inputMode="decimal"
              placeholder={t("valueAmount")}
              aria-label={t("valueAmount")}
              className={ui.input}
            />
            <input
              name="value_currency"
              maxLength={3}
              placeholder={t("currency")}
              aria-label={t("currency")}
              className={ui.input}
            />
            <button type="submit" className={ui.button}>
              {t("add")}
            </button>
          </form>
        )}
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <ul className={ui.card}>
          {enquiries === null && <li className="text-sm text-muted-foreground">{t("loading")}</li>}
          {enquiries?.length === 0 && <li className="text-sm text-muted-foreground">{t("empty")}</li>}
          {enquiries?.length ? (
            <li className="text-xs text-muted-foreground">{t("count", { count: enquiries.length })}</li>
          ) : null}
          {enquiries?.map((enquiry) => (
            <li key={enquiry.public_id} className="flex items-start justify-between gap-4">
              <div>
                <p className="font-medium">
                  {enquiry.number} · {enquiry.subject}
                </p>
                <p className="text-sm text-muted-foreground">
                  {contactLine(enquiry)}
                </p>
                <p className="text-sm">
                  {enquiry.status} · {enquiry.value.amount} {enquiry.value.currency}
                </p>
              </div>
              <div className="flex flex-wrap justify-end gap-2">
                {perms.can(ENQUIRY_CODES.transition) &&
                  enquiry.transitions.map((transition) => (
                    <button
                      key={transition.to}
                      type="button"
                      className="text-sm underline"
                      onClick={() => handleTransition(enquiry, transition)}
                    >
                      {t("moveTo", { status: transition.to })}
                    </button>
                  ))}
                {perms.can(ENQUIRY_CODES.delete) && (
                  <button type="button" className="text-sm underline" onClick={() => handleDelete(enquiry)}>
                    {t("delete")}
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      </>
    );

  return (
    <main className="flex min-h-screen flex-col items-center gap-6 p-8 font-sans">
      <h1 className="text-2xl font-bold tracking-tight">{t("title")}</h1>
      {content}
      <Link className="text-xs text-muted-foreground underline" href="/">
        {t("home")}
      </Link>
    </main>
  );
}
