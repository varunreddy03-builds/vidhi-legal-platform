import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import TodoVerify from "@/components/recovery/TodoVerify";
import { GUIDE_EN } from "./guideStrings";
import { FACT_STRING_KEYS, FACTS, LAST_VERIFIED, PORTAL_RULES, isVerified, needsVerifying, routeFor, type Fact, type FactId } from "./portalRules";

const SRC = path.resolve(__dirname, "../..");
const ids = Object.keys(FACTS) as FactId[];

function sourceFiles(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const full = path.join(dir, e.name);
    if (e.isDirectory()) return sourceFiles(full);
    return /\.(ts|tsx)$/.test(e.name) && !/\.test\.(ts|tsx)$/.test(e.name) ? [full] : [];
  });
}

describe("Legal Recovery rules: one config file, every fact marked until verified", () => {
  it("every fact has text, a use and a status, and none is verified without a recorded day", () => {
    for (const id of ids) {
      const f: Fact = FACTS[id];
      expect(f.text.length, id).toBeGreaterThan(5);
      expect(f.usedFor.length, id).toBeGreaterThan(5);
      expect(["TODO: verify", "verified"], id).toContain(f.status);
      if (f.status === "verified") expect(LAST_VERIFIED, `${id} is marked verified but LAST_VERIFIED is empty`).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    }
    if (LAST_VERIFIED) {
      expect(LAST_VERIFIED).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      expect(new Date(`${LAST_VERIFIED}T00:00:00Z`).getTime()).toBeLessThanOrEqual(Date.now()); // a verification day cannot be in the future
    }
    expect(PORTAL_RULES.lastVerified).toBe(LAST_VERIFIED);
  });

  it("nothing has been verified yet, and the config says so for every fact", () => {
    expect(LAST_VERIFIED).toBe("");
    expect(ids.every((id) => FACTS[id].status === "TODO: verify")).toBe(true);
    expect(needsVerifying(ids)).toBe(true);
  });

  it("the TODO: verify mark shows while a fact is unverified and goes only when it is verified AND a day is recorded", () => {
    const some: Record<string, Fact> = { a: { text: "A fact sentence.", status: "verified", usedFor: "a test" }, b: { text: "Another fact.", status: "TODO: verify", usedFor: "a test" } };
    expect(needsVerifying(["a"] as unknown as FactId[], some, "2026-11-05")).toBe(false);
    expect(needsVerifying(["a"] as unknown as FactId[], some, "")).toBe(true); // "verified" without a day does not count
    expect(needsVerifying(["a", "b"] as unknown as FactId[], some, "2026-11-05")).toBe(true);
    expect(isVerified(some.a, "2026-11-05")).toBe(true);
    const html = renderToStaticMarkup(<TodoVerify ids={["portalExists"]} />);
    expect(html).toContain("TODO: verify");
    expect(html).toContain('data-testid="todo-verify"');
  });

  it("no fact sentence, address or date is written anywhere else in the front end", () => {
    const own = path.join(SRC, "lib", "recovery", "portalRules.ts");
    const others = sourceFiles(SRC).filter((f) => f !== own);
    const marks = [FACTS.portalUrl.text, FACTS.effectiveDate.text, "conciliation, mediation", ...ids.map((id) => FACTS[id].text)];
    for (const file of others) {
      const text = fs.readFileSync(file, "utf8");
      for (const m of marks) expect(text.includes(m), `${path.relative(SRC, file)} repeats a fact from portalRules.ts: "${m.slice(0, 50)}"`).toBe(false);
    }
  });

  it("every guide sentence that sounds like a legal or government fact is tied to a fact (so it carries the mark)", () => {
    const sounds = /government|\bODR\b|portal|formal service|arbitration|court|Udyam registration is|mandatory|must\b|free\b/i;
    // Wording that is not a fact: questions, buttons, labels, framing of the person's own choices, and statements about what VIDHI itself does.
    const NOT_FACTS: Record<string, string> = {
      sub: "describes the steps of the guide",
      steps: "step labels",
      selfDeclared: "says what VIDHI itself does and does not check",
      udyamNote: "says what VIDHI itself does and does not check",
      portalRef: "a label for what the person types",
      q1: "a question",
      portalWhy: "a label in front of the 'who it is for' fact, which carries its own mark",
      portalChecklist: "a heading in front of the checklist, which carries its own mark",
      portalOpen: "a button label",
      portalFiled: "a button label",
      portalSkip: "a button label",
      unsureTitle: "a heading",
      noticeFraming: "advice about the person's own choice, with no fact in it",
      lawyer: "a button label",
      iSentIt: "a button label",
      markEscalated: "a button label",
      escalateTitle: "a heading",
      escalateCta: "a button label",
      emailNote: "tied to a fact through FACT_STRING_KEYS",
      needApproval: "says what VIDHI requires before sending",
      email: "a button label",
      download: "a button label",
      smallIntro: "describes the steps of the guide",
    };
    const bad: string[] = [];
    for (const [key, value] of Object.entries(GUIDE_EN)) {
      if (typeof value !== "string" || !sounds.test(value)) continue;
      if (key in FACT_STRING_KEYS || key in NOT_FACTS) continue;
      bad.push(`${key}: ${value.slice(0, 70)}`);
    }
    expect(bad, `these sentences sound like facts but are not tied to portalRules.ts (add them to FACT_STRING_KEYS, or to NOT_FACTS here with the reason):\n${bad.join("\n")}`).toEqual([]);
    for (const [key, factIds] of Object.entries(FACT_STRING_KEYS)) {
      expect(key in GUIDE_EN, `${key} is in FACT_STRING_KEYS but not in the guide strings`).toBe(true);
      for (const id of factIds) expect(id in FACTS, `${key} points to an unknown fact ${id}`).toBe(true);
    }
  });

  it("the routing only decides which card is shown first", () => {
    expect(routeFor("yes", "business")).toBe("portal_first");
    expect(routeFor("yes", "individual")).toBe("skip_individual");
    expect(routeFor("no", "business")).toBe("skip_not_registered");
    expect(routeFor("no", "individual")).toBe("skip_individual");
    expect(routeFor("not_sure", "business")).toBe("unsure");
    expect(routeFor("not_sure", "individual")).toBe("unsure");
  });
});
