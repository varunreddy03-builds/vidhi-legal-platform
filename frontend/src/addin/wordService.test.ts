import { describe, expect, it } from "vitest";
import { GROUPS, STATUS_STYLE, commentText, groupIssues, idFor, occurrenceBefore, searchable, type Issue } from "./wordService";

const issue = (over: Partial<Issue>): Issue => ({
  id: "i1", group: "defect", paragraph_id: "p1", start_index: 0, end_index: 3, text: "___", defect_type: "blank", status_label: null, suggested_replacement: null, reviewer_source_note: "", message: "A blank line is left in the text.", ...over,
});

describe("Word add-in helpers", () => {
  it("paragraph ids follow Word's order, from p1", () => {
    expect([0, 1, 9].map(idFor)).toEqual(["p1", "p2", "p10"]);
  });

  it("the n-th match in a paragraph is the one at the finding's position", () => {
    const t = "Section 302 IPC and again Section 302 IPC.";
    expect(occurrenceBefore(t, "302 IPC", t.indexOf("302 IPC"))).toBe(0);
    expect(occurrenceBefore(t, "302 IPC", t.lastIndexOf("302 IPC"))).toBe(1);
    expect(occurrenceBefore(t, "", 5)).toBe(0);
    // an emoji is one character for the server but two for JavaScript: the count still lands on the right match
    const e = "😀 302 IPC then 302 IPC";
    expect(occurrenceBefore(e, "302 IPC", Array.from(e).indexOf("3", 8))).toBe(1);
  });

  it("only text Word can search for is searched; the rest is located by its paragraph", () => {
    expect(searchable("302 IPC")).toBe(true);
    expect(searchable("")).toBe(false);
    expect(searchable("a^b")).toBe(false);
    expect(searchable("x".repeat(256))).toBe(false);
  });

  it("findings are grouped into the three panel sections", () => {
    const g = groupIssues([issue({ id: "a", group: "authority" }), issue({ id: "b", group: "code_replacement" }), issue({ id: "c" }), issue({ id: "d" })]);
    expect(g.authority.map((i) => i.id)).toEqual(["a"]);
    expect(g.code_replacement.map((i) => i.id)).toEqual(["b"]);
    expect(g.defect.map((i) => i.id)).toEqual(["c", "d"]);
    expect(GROUPS.map((x) => x.key)).toEqual(["authority", "code_replacement", "defect"]);
  });

  it("the three labels are written out and coloured green, amber and red", () => {
    expect(STATUS_STYLE.VERIFIED.text).toBe("Verified");
    expect(STATUS_STYLE.PARTLY_VERIFIED.text).toBe("Partly verified");
    expect(STATUS_STYLE.NOT_SUPPORTED.text).toBe("Not supported");
    expect(STATUS_STYLE.VERIFIED.className).toContain("green");
    expect(STATUS_STYLE.PARTLY_VERIFIED.className).toContain("amber");
    expect(STATUS_STYLE.NOT_SUPPORTED.className).toContain("red");
  });

  it("the comment is neutral, carries the source note and ends with 'A lawyer decides.'", () => {
    const text = commentText(issue({ group: "authority", status_label: "PARTLY_VERIFIED", message: "The case was found; some details differ.", reviewer_source_note: "Source: open dataset." }));
    expect(text).toBe("Citation: Partly verified. The case was found; some details differ. Source: open dataset. A lawyer decides.");
    expect(commentText(issue({}))).toBe("A blank line is left in the text. A lawyer decides.");
    expect(text).not.toMatch(/\b(lied|false|fake|fabricat)/i);
  });
});
