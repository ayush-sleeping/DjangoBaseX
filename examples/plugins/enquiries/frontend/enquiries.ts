/**
 * The enquiries API, for this plugin's pages (the plugin's own src/core/lib equivalent). Every call
 * goes through @/core/lib/api, never an inline fetch() (AGENTS.md § 3).
 */
import { api, type Page } from "@/core/lib/api";

export const ENQUIRY_CODES = {
  view: "enquiries.enquiries.view",
  create: "enquiries.enquiries.create",
  update: "enquiries.enquiries.update",
  transition: "enquiries.enquiries.transition",
  delete: "enquiries.enquiries.delete",
} as const;

export type EnquiryStatus = "new" | "contacted" | "quoted" | "won" | "lost";

export type EnquiryTransition = { to: string; needs_reason: boolean };

export type Enquiry = {
  public_id: string;
  number: string;
  contact_name: string;
  contact_email: string;
  subject: string;
  message: string;
  status: EnquiryStatus;
  value: { amount: string; currency: string };
  allowed_transitions: string[];
  transitions: EnquiryTransition[];
  origin: string;
  source_ref: string;
  created_at: string;
};

export type NewEnquiry = {
  contact_name: string;
  contact_email: string;
  subject: string;
  message: string;
  value_amount: string;
  value_currency: string;
};

const ENQUIRIES = "/api/enquiries/";

export async function listEnquiries(): Promise<Page<Enquiry>> {
  return api<Page<Enquiry>>(ENQUIRIES, { cache: "no-store" });
}

export async function createEnquiry(input: NewEnquiry): Promise<Enquiry> {
  return api<Enquiry>(ENQUIRIES, { method: "POST", body: JSON.stringify(input) });
}

export async function transitionEnquiry(publicId: string, to: string, reason?: string): Promise<Enquiry> {
  return api<Enquiry>(`${ENQUIRIES}${encodeURIComponent(publicId)}/transition/`, {
    method: "POST",
    body: JSON.stringify(reason ? { to, reason } : { to }),
  });
}

export async function deleteEnquiry(publicId: string): Promise<void> {
  await api<void>(`${ENQUIRIES}${encodeURIComponent(publicId)}/`, { method: "DELETE" });
}
