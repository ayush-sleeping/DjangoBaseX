"use client";

// Client component: notes are authenticated data, and the session is an httpOnly cookie.
import Link from "next/link";
import { type FormEvent, useCallback, useEffect, useState } from "react";

import { fieldErrors } from "@/core/lib/api";
import { usePermissions } from "@/core/lib/permissions";

import { createNote, deleteNote, listNotes, type Note, NOTE_CODES } from "./notes";

const ui = {
  card: "w-full max-w-xl space-y-3 rounded-xl border border-border p-6",
  input: "w-full rounded-md border border-input px-3 py-2",
  button:
    "rounded-md bg-primary px-3 py-2 text-sm text-primary-foreground disabled:opacity-50",
};

export default function NotesPage() {
  const perms = usePermissions();
  const [notes, setNotes] = useState<Note[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const canView = perms.can(NOTE_CODES.view);

  const load = useCallback(() => {
    listNotes()
      .then((page) => setNotes(page.results))
      .catch(() => setError("Could not load your notes."));
  }, []);

  useEffect(() => {
    if (canView) load();
  }, [canView, load]);

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    try {
      await createNote(String(data.get("title") ?? ""), String(data.get("body") ?? ""));
      form.reset();
      setError(null);
      load();
    } catch (caught) {
      setError(fieldErrors(caught).title?.[0] ?? "Could not save the note.");
    }
  }

  async function handleDelete(note: Note) {
    try {
      await deleteNote(note.public_id);
      load();
    } catch {
      setError("Could not delete the note.");
    }
  }

  let content;
  if (perms.status === "loading") content = <p className="text-sm text-muted-foreground">Checking your session…</p>;
  else if (!perms.user)
    content = (
      <Link className="text-sm underline" href="/login">
        Sign in to see your notes
      </Link>
    );
  else if (!canView) content = <p className="text-sm">You don&apos;t have permission to view notes.</p>;
  else
    content = (
      <>
        {perms.can(NOTE_CODES.create) && (
          <form onSubmit={handleCreate} className={ui.card}>
            <input name="title" placeholder="Title" aria-label="Title" className={ui.input} />
            <textarea name="body" placeholder="Note" aria-label="Note" className={ui.input} />
            <button type="submit" className={ui.button}>
              Add note
            </button>
          </form>
        )}
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <ul className={ui.card}>
          {notes === null && <li className="text-sm text-muted-foreground">Loading…</li>}
          {notes?.length === 0 && <li className="text-sm text-muted-foreground">No notes yet.</li>}
          {notes?.map((note) => (
            <li key={note.public_id} className="flex items-start justify-between gap-4">
              <div>
                <p className="font-medium">{note.title}</p>
                {note.body && <p className="text-sm text-muted-foreground">{note.body}</p>}
              </div>
              {perms.can(NOTE_CODES.delete) && (
                <button type="button" className="text-sm underline" onClick={() => handleDelete(note)}>
                  Delete
                </button>
              )}
            </li>
          ))}
        </ul>
      </>
    );

  return (
    <main className="flex min-h-screen flex-col items-center gap-6 p-8 font-sans">
      <h1 className="text-2xl font-bold tracking-tight">Notes</h1>
      {content}
      <Link className="text-xs text-muted-foreground underline" href="/">
        Home
      </Link>
    </main>
  );
}
