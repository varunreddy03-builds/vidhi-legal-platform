import { describe, expect, it } from "vitest";
import { LANGUAGES } from "@/lib/languages";
import { en } from "./en";

const files = import.meta.glob<{ default: Record<string, string> }>("./locales/*.ts", { eager: true });
const catalog = (code: string) => files[`./locales/${code}.ts`]?.default;
// Added with the sign-in polish: shown in English until the translators reach them (English is the fallback).
const NEW_ENGLISH_ONLY = new Set(["more.clients", "toolkit.ld.title", "toolkit.ld.body", "home.tk.title", "home.tk.sub", "home.rec.small", "start.d3.open", "login.google.off", "login.err.cancelled", "login.err.suspended", "nav.toolkit", "nav.recovery", "grp.more", "start.tk.tag", "start.tk.title", "start.tk.cta", "start.tk.body", "toolkit.sub", "toolkit.off", "toolkit.soon", "toolkit.ac.title", "toolkit.ac.body", "toolkit.dl.title", "toolkit.dl.body", "toolkit.oc.title", "toolkit.oc.body", "toolkit.pf.title", "toolkit.pf.body", "toolkit.note", "nav.intelligence", "nav.law", "grp.katalyst", "more.recovery.sub", "intel.sub", "intel.ask.body", "intel.research.body", "intel.matters.body", "intel.drafts.body", "intel.law.body", "nav.judgments", "intel.judgments.body", "nav.legaldir", "nav.vault", "nav.tax"]);
const placeholders = (s: string) => (s.match(/\{[a-z]+\}/g) ?? []).sort().join(",");

describe("languages", () => {
  it("lists English plus the 22 languages of the Eighth Schedule", () => {
    expect(LANGUAGES).toHaveLength(23);
    expect(new Set(LANGUAGES.map((l) => l.code)).size).toBe(23);
  });

  it("has a catalog file for every language except English", () => {
    for (const l of LANGUAGES.filter((x) => x.code !== "en")) expect(catalog(l.code), l.code).toBeTruthy();
  });

  it("right-to-left languages are marked", () => {
    expect(LANGUAGES.filter((l) => l.dir === "rtl").map((l) => l.code).sort()).toEqual(["ks", "sd", "ur"]);
  });

  for (const l of LANGUAGES.filter((x) => x.code !== "en")) {
    it(`${l.code}: only known keys, placeholders kept, nothing empty`, () => {
      const c = catalog(l.code) ?? {};
      for (const [k, v] of Object.entries(c)) {
        expect(k in en, `${l.code} has unknown key ${k}`).toBe(true);
        expect(v.trim().length, `${l.code}.${k} is empty`).toBeGreaterThan(0);
        expect(placeholders(v), `${l.code}.${k} must keep the same {placeholders}`).toBe(placeholders(en[k as keyof typeof en]));
      }
    });
    if (l.quality === "full")
      it(`${l.code}: complete (every English key is translated)`, () => {
        const c = catalog(l.code) ?? {};
        const missing = Object.keys(en).filter((k) => !(k in c) && k !== "home.intel.title" && k !== "home.rec.title" && k !== "rec.title" && !NEW_ENGLISH_ONLY.has(k));
        expect(missing).toEqual([]);
      });
  }
});
