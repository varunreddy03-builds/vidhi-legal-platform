import { describe, expect, it } from "vitest";
import { buildOutline, toLines } from "./taxOutline";

const base = { authority: "The Assessing Officer, Ward 3", reference: "ABC/123", noticeDate: "2026-10-01", period: "FY 2024-25", taxpayer: "Asha Traders", sectionNamed: "the provision typed by the person", points: ["Cash deposits", "Late filing"], documents: ["Bank statement"] };

describe("tax reply outline", () => {
  it("uses only what was typed and numbers each point", () => {
    const t = buildOutline(base);
    expect(t).toContain("NOT FOR FILING");
    expect(t).toContain("The Assessing Officer, Ward 3");
    expect(t).toContain("3.1 Point raised: Cash deposits");
    expect(t).toContain("3.2 Point raised: Late filing");
    expect(t).toContain("1. Bank statement");
  });
  it("leaves every legal point blank and states no law of its own", () => {
    const t = buildOutline({ ...base, sectionNamed: "" });
    expect(t).toContain("[Provision: to be filled by the advocate]");
    expect(t.match(/Legal position: \[Provision and authority, with the source checked: to be filled by the advocate\]/g)).toHaveLength(2);
    expect(t).not.toMatch(/\bSection \d|\bsec\. \d|\d+(\.\d+)?\s?%|Rs\.? ?\d|₹/i); // no statute, rate or amount of its own
  });
  it("copes with empty input and messy lines", () => {
    expect(buildOutline({ authority: "", reference: "", noticeDate: "", period: "", taxpayer: "", sectionNamed: "", points: [], documents: [] })).toContain("[Point raised in the notice]");
    expect(toLines("  a  b \n\n c\r\n")).toEqual(["a b", "c"]);
  });
});
