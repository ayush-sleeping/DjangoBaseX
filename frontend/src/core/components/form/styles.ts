/** The shared control look: every input, select and textarea is one height and one border. */
export const inputClass =
  "h-(--control-h) w-full rounded-md border border-input bg-background px-3 text-sm text-foreground " +
  "placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring " +
  "disabled:cursor-not-allowed disabled:opacity-60 aria-invalid:border-destructive";

export const textareaClass = inputClass.replace("h-(--control-h)", "min-h-24 py-2");
