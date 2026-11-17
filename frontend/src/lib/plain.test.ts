import { describe, expect, it } from "vitest";
import { EXAMPLE_QUESTIONS, firstName, PLAIN_CLAIM_KIND, PLAIN_CLAIM_STATUS, PLAIN_MATTER_STATUS } from "./plain";

describe("firstName", () => {
  it.each([
    ["Anita Sharma", "Anita"],
    ["  Ravi   Kumar  ", "Ravi"],
    ["Meena", "Meena"],
    ["", "friend"],
    ["   ", "friend"],
    [null, "friend"],
    [undefined, "friend"],
  ])("%j -> %s", (input, expected) => {
    expect(firstName(input as string | null | undefined)).toBe(expected);
  });
});

describe("plain-language labels", () => {
  it("covers every verification status the engine can report", () => {
    for (const s of ["VERIFIED", "PARTIALLY_VERIFIED", "UNSUPPORTED", "UNVERIFIED", "UNAVAILABLE"]) {
      expect(PLAIN_CLAIM_STATUS[s]?.label, s).toBeTruthy();
    }
  });

  it("only calls a claim backed up when the engine verified it", () => {
    const backedUp = Object.entries(PLAIN_CLAIM_STATUS).filter(([, v]) => v.tone === "good");
    expect(backedUp.map(([k]) => k)).toEqual(["VERIFIED"]);
  });

  it("warns about anything that is not verified", () => {
    expect(PLAIN_CLAIM_STATUS.UNSUPPORTED.label).toMatch(/check before relying/i);
    expect(PLAIN_CLAIM_STATUS.UNVERIFIED.label).toBe(PLAIN_CLAIM_STATUS.UNSUPPORTED.label);
  });

  it("names every claim kind and matter status", () => {
    expect(Object.keys(PLAIN_CLAIM_KIND).sort()).toEqual(["ABSENCE", "FACTUAL", "LEGAL", "PROCEDURAL"]);
    expect(Object.keys(PLAIN_MATTER_STATUS).sort()).toEqual(["CLOSED", "ON_HOLD", "OPEN"]);
  });

  it("offers example questions that promise no outcome", () => {
    expect(EXAMPLE_QUESTIONS.length).toBeGreaterThanOrEqual(3);
    for (const q of EXAMPLE_QUESTIONS) expect(q).not.toMatch(/guarantee|you will win|certainly/i);
  });
});
