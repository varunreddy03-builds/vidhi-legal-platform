/**
 * Talks to the open Word document through Office.js (WordApi 1.4 or later) and to the VIDHI backend.
 * The side panel is served from the app's own address, so the sign-in cookie applies and nothing is sent anywhere else.
 * Office.js is loaded only on the add-in page (loadOffice), never in the rest of the app.
 */
import { apiPost } from "@/lib/api";

// The few Office.js shapes this file uses. (No extra package: the full typings are not installed.)
/* eslint-disable @typescript-eslint/no-explicit-any */
declare const Word: any;
declare const Office: any;

export type StatusLabel = "VERIFIED" | "PARTLY_VERIFIED" | "NOT_SUPPORTED";
export interface Issue {
  id: string;
  group: "authority" | "code_replacement" | "defect";
  paragraph_id: string;
  start_index: number;
  end_index: number;
  text: string;
  defect_type: string;
  status_label: StatusLabel | null;
  suggested_replacement: string | null;
  reviewer_source_note: string;
  message: string;
  caveat?: string;
  sections?: string[];
}
export interface DateItem {
  paragraph_id: string;
  start_index: number;
  end_index: number;
  text: string;
  date: string | null;
  flags: string[];
  message: string;
}
export interface Analysis {
  issues: Issue[];
  dates: DateItem[];
  checks: Record<string, string>;
  counts: Record<string, unknown>;
  neutral_note: string;
  caveat: string;
}
export interface Para {
  id: string;
  text: string;
}

const OFFICE_JS = "https://appsforoffice.microsoft.com/lib/1/hosted/office.js";

/** Loads Office.js once, and resolves when Word is ready. Rejects (after a wait) when the page is not open inside Word. */
export function loadOffice(): Promise<void> {
  return new Promise((resolve, reject) => {
    const ready = () => {
      Office.onReady((info: { host?: string }) => (info.host === "Word" ? resolve() : reject(new Error("This panel works inside Microsoft Word."))));
    };
    if (typeof Office !== "undefined") return ready();
    const s = document.createElement("script");
    s.src = OFFICE_JS;
    s.onload = ready;
    s.onerror = () => reject(new Error("Office.js could not be loaded."));
    document.head.appendChild(s);
    setTimeout(() => reject(new Error("This panel works inside Microsoft Word.")), 15000);
  });
}

/** The paragraph ids are p1, p2, ... in the order Word lists them (the same order the Word-file check uses). */
export const idFor = (index: number) => `p${index + 1}`;

export async function readParagraphs(): Promise<Para[]> {
  return Word.run(async (context: any) => {
    const paragraphs = context.document.body.paragraphs;
    paragraphs.load("items/text");
    await context.sync();
    return paragraphs.items.map((p: { text: string }, i: number) => ({ id: idFor(i), text: p.text }));
  });
}

export function analyze(paragraphs: Para[]): Promise<Analysis> {
  return apiPost<Analysis>("/v1/katalyst/analyze-text", { paragraphs });
}

/** The server counts characters as Unicode code points, JavaScript counts UTF-16 units: they differ only for characters such as emoji. */
export const unitIndex = (text: string, codePoints: number) => Array.from(text).slice(0, codePoints).join("").length;

/** How many times `needle` appears in `text` before position `start` (counted in code points): the n-th match in the paragraph is the one at that position. */
export function occurrenceBefore(text: string, needle: string, start: number): number {
  if (!needle) return 0;
  const limit = unitIndex(text, start);
  let n = 0;
  for (let at = text.indexOf(needle); at !== -1 && at < limit; at = text.indexOf(needle, at + 1)) n++;
  return n;
}

/** Word's search treats ^ as a special character and takes at most 255 characters; those texts are located by their paragraph instead. */
export const searchable = (needle: string) => needle.length > 0 && needle.length <= 255 && !needle.includes("^");

async function rangeFor(context: any, issue: { paragraph_id: string; start_index: number; text: string }, paragraphs: Para[]) {
  const index = paragraphs.findIndex((p) => p.id === issue.paragraph_id);
  if (index < 0) throw new Error("This paragraph is no longer in the document. Scan again.");
  const para = context.document.body.paragraphs;
  para.load("items");
  await context.sync();
  const p = para.items[index];
  p.load("text");
  await context.sync();
  if (p.text !== paragraphs[index].text) throw new Error("The document has changed since the scan. Scan again.");
  if (!searchable(issue.text)) return p.getRange("Whole");
  const hits = p.search(issue.text, { matchCase: true });
  hits.load("items");
  await context.sync();
  return hits.items[occurrenceBefore(p.text, issue.text, issue.start_index)] ?? p.getRange("Whole");
}

/** Click-to-locate: selects the exact words in the document and scrolls to them. */
export async function locate(issue: { paragraph_id: string; start_index: number; text: string }, paragraphs: Para[]): Promise<void> {
  await Word.run(async (context: any) => {
    const range = await rangeFor(context, issue, paragraphs);
    range.select();
    await context.sync();
  });
}

/** Puts a native Word comment on the words. */
export async function comment(issue: Issue, paragraphs: Para[], text: string): Promise<void> {
  await Word.run(async (context: any) => {
    const range = await rangeFor(context, issue, paragraphs);
    range.insertComment(text);
    await context.sync();
  });
}

/** Replaces the words with Track Changes turned on, so the lawyer accepts or rejects it in Word. The mode the person had is put back afterwards. */
export async function replaceTracked(issue: Issue, paragraphs: Para[], replacement: string): Promise<void> {
  await Word.run(async (context: any) => {
    const range = await rangeFor(context, issue, paragraphs);
    context.document.load("changeTrackingMode");
    await context.sync();
    const before = context.document.changeTrackingMode;
    context.document.changeTrackingMode = Word.ChangeTrackingMode.trackAll;
    range.insertText(replacement, "Replace");
    await context.sync();
    context.document.changeTrackingMode = before;
    await context.sync();
  });
}

export const GROUPS: { key: "authority" | "code_replacement" | "defect"; title: string }[] = [
  { key: "authority", title: "Authority and citations" },
  { key: "code_replacement", title: "Old code to new code (IPC, CrPC, Evidence Act)" },
  { key: "defect", title: "Pre-filing defects and blanks" },
];

export function groupIssues(issues: Issue[]): Record<"authority" | "code_replacement" | "defect", Issue[]> {
  const out = { authority: [] as Issue[], code_replacement: [] as Issue[], defect: [] as Issue[] };
  for (const i of issues) out[i.group].push(i);
  return out;
}

/** Green, amber, red: the three honest labels. Colour is never the only signal; the label is written out too. */
export const STATUS_STYLE: Record<StatusLabel, { text: string; className: string }> = {
  VERIFIED: { text: "Verified", className: "border-green-600 text-green-700 dark:text-green-400" },
  PARTLY_VERIFIED: { text: "Partly verified", className: "border-amber-600 text-amber-700 dark:text-amber-400" },
  NOT_SUPPORTED: { text: "Not supported", className: "border-red-600 text-red-700 dark:text-red-400" },
};

/** The comment text the one-click comment puts in Word: neutral, with the reviewer's source and the fixed caveat. */
export function commentText(i: Issue): string {
  return [i.status_label ? `Citation: ${STATUS_STYLE[i.status_label].text}.` : "", i.message, i.reviewer_source_note, "A lawyer decides."].filter(Boolean).join(" ").slice(0, 1500);
}
