/**
 * The notes API, for this plugin's pages (the plugin's own src/core/lib equivalent). Every call
 * goes through @/core/lib/api, never an inline fetch() (AGENTS.md § 3).
 */
import { api, type Page } from "@/core/lib/api";

export const NOTE_CODES = {
  view: "notes.notes.view",
  create: "notes.notes.create",
  delete: "notes.notes.delete",
} as const;

export type Note = { public_id: string; title: string; body: string; created_at: string };

const NOTES = "/api/notes/";

export async function listNotes(): Promise<Page<Note>> {
  return api<Page<Note>>(NOTES, { cache: "no-store" });
}

export async function createNote(title: string, body: string): Promise<Note> {
  return api<Note>(NOTES, { method: "POST", body: JSON.stringify({ title, body }) });
}

export async function deleteNote(publicId: string): Promise<void> {
  await api<void>(`${NOTES}${encodeURIComponent(publicId)}/`, { method: "DELETE" });
}
