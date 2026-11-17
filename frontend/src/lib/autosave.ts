// Keeping what a person types. A copy is held on the device as they type (so a dropped line, a closed tab or a flat battery loses nothing), and the text is sent to the server a few
// seconds after they stop. Pure helpers here; the draft editor uses them.

export type SaveState = "saved" | "dirty" | "saving" | "offline" | "failed";

/** Seconds of quiet after the last keystroke before the text is sent to the server. */
export const AUTOSAVE_AFTER_MS = 8000;

export interface LocalCopy {
  title: string;
  body: string;
  at: number;
}

const key = (id: string) => `vidhi-draft-${id}`;

export function readLocal(id: string): LocalCopy | null {
  try {
    const raw = localStorage.getItem(key(id));
    if (!raw) return null;
    const v = JSON.parse(raw) as Partial<LocalCopy>;
    return typeof v.title === "string" && typeof v.body === "string" ? { title: v.title, body: v.body, at: Number(v.at) || 0 } : null;
  } catch {
    return null; // blocked or full storage: the server copy still works
  }
}

export function writeLocal(id: string, title: string, body: string): void {
  try {
    localStorage.setItem(key(id), JSON.stringify({ title, body, at: Date.now() } satisfies LocalCopy));
  } catch {
    /* blocked or full: nothing more can be done here */
  }
}

export function clearLocal(id: string): void {
  try {
    localStorage.removeItem(key(id));
  } catch {
    /* ignore */
  }
}

/** Is the copy on this device different from the saved draft? Then the person is asked whether to bring it back. */
export function differsFromSaved(local: LocalCopy | null, saved: { title: string; body: string }): boolean {
  return !!local && (local.title !== saved.title || local.body !== saved.body);
}

/** One plain sentence for each state: what is true, and what to do if anything. */
export function statusText(state: SaveState): string {
  switch (state) {
    case "saved":
      return "All changes saved.";
    case "dirty":
      return "Unsaved changes: saving in a few seconds.";
    case "saving":
      return "Saving…";
    case "offline":
      return "No connection. Your text is kept on this phone and will be saved when you are back online.";
    case "failed":
      return "Could not save. Your text is kept on this phone. Press Save to try again.";
  }
}
