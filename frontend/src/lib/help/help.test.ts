import { describe, expect, it } from "vitest";
import en from "./en";
import type { HelpContent } from "./types";
import { HELP_LANGUAGES } from "./useHelp";

const files = import.meta.glob<{ default: HelpContent }>("./*.ts", { eager: true });
const content = (c: string) => files[`./${c}.ts`].default;
// letters of each language's own script (a translation that is mostly Latin letters was not translated)
const SCRIPT: Record<string, [number, number]> = { hi: [0x0900, 0x097f], mr: [0x0900, 0x097f], te: [0x0c00, 0x0c7f], ta: [0x0b80, 0x0bff], bn: [0x0980, 0x09ff], gu: [0x0a80, 0x0aff] };
const share = (text: string, [lo, hi]: [number, number]) => {
  const letters = [...text].filter((ch) => /\p{L}|\p{M}/u.test(ch));
  return letters.length ? letters.filter((ch) => ch.charCodeAt(0) >= lo && ch.charCodeAt(0) <= hi).length / letters.length : 0;
};
const texts = (h: HelpContent) => [h.note, ...h.tour.flatMap((t) => [t.title, t.text]), ...h.sections.flatMap((s) => [s.title, ...s.items.flatMap((i) => [i.q, i.a])])];

describe("help content", () => {
  it("exists for English plus Hindi, Telugu, Tamil, Bengali, Marathi and Gujarati", () => {
    expect([...HELP_LANGUAGES]).toEqual(["en", "hi", "te", "ta", "bn", "mr", "gu"]);
    for (const c of HELP_LANGUAGES) expect(files[`./${c}.ts`], c).toBeTruthy();
  });

  it.each(HELP_LANGUAGES.filter((c) => c !== "en"))("%s has exactly the structure of the English reference with nothing empty", (c) => {
    const h = content(c);
    expect(h.tour).toHaveLength(en.tour.length);
    expect(h.sections.map((s) => s.items.length)).toEqual(en.sections.map((s) => s.items.length));
    expect(Object.keys(h.ui).sort()).toEqual(Object.keys(en.ui).sort());
    for (const t of texts(h)) expect(t.trim().length, `${c}: empty text`).toBeGreaterThan(2);
    for (const k of Object.keys(en.ui) as (keyof typeof en.ui)[]) expect(h.ui[k].trim().length, `${c}.ui.${k}`).toBeGreaterThan(0);
    expect(h.ui.step).toContain("{n}");
    expect(h.ui.step).toContain("{total}");
  });

  it.each(Object.keys(SCRIPT))("%s is written in its own script, says it is an unreviewed translation, and keeps product names unchanged", (c) => {
    const h = content(c);
    expect(h.note.length).toBeGreaterThan(20);
    expect(share(texts(h).join(" "), SCRIPT[c])).toBeGreaterThan(0.6);
    for (const name of ["Legal Intelligence", "Legal Recovery"]) expect(h.sections.map((s) => s.title).concat(h.sections.flatMap((s) => s.items.map((i) => i.a))).join(" ")).toContain(name);
    expect(texts(h).join(" ")).toContain("VIDHI");
  });

  it("never promises a result, never claims law is verified, and says it is not legal advice", () => {
    const all = texts(en).join(" ").toLowerCase();
    expect(all).not.toMatch(/guarantee|you will win|always correct|100%/);
    expect(all).toContain("not legal advice");
    expect(en.note).toBe("");
    // every translation says in its own words that it is not legal advice; check the notes are not copies of the English one
    for (const c of Object.keys(SCRIPT)) expect(content(c).note).not.toBe(en.note);
  });

  it("has the same questions in the same order as English, so a person switching language lands on the same answer", () => {
    for (const c of HELP_LANGUAGES) {
      const h = content(c);
      expect(h.sections.map((s) => s.items.length)).toEqual([3, 2, 3, 3]);
      expect(h.tour.length).toBe(5);
    }
  });
});
describe("pages that exist in English only so far", () => {
  const extra = en.extra ?? [];
  const text = extra.flatMap((s) => [s.title, ...s.items.flatMap((i) => [i.q, i.a])]).join(" ");

  it("are in the English file only, so a translation never claims them", () => {
    expect(extra.length).toBeGreaterThanOrEqual(4);
    for (const c of HELP_LANGUAGES.filter((l) => l !== "en")) expect(content(c).extra, c).toBeUndefined();
  });

  it("cover the tasks people do: citations, template drafts, files, connection, team, plans, law and judgments", () => {
    for (const word of ["Authority Check", "Check this draft", "templates", "scanned", "connection dropped", "save by itself", "Who can do what", "Send for review", "Free and Pro", "theme and language", "not reviewed", "judgment", "Deadline engine", "Old-code to new-code", "Pre-filing defect check", "List of dates"]) {
      expect(text.toLowerCase(), word).toContain(word.toLowerCase());
    }
  });

  it("have real answers, promise no result, claim no verified law and never call anyone dishonest", () => {
    for (const s of extra) for (const i of s.items) expect(i.a.length, i.q).toBeGreaterThan(60);
    expect(text.toLowerCase()).not.toMatch(/guarantee|you will win|always correct|100%|\blied\b|\bliar\b|dishonest/);
    expect(text).toContain("not a check of the law");
    expect(text).toContain("not findings that a reference is wrong");
  });
});
