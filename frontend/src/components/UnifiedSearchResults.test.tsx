import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import UnifiedSearchResults, { type UnifiedItem, type UnifiedResponse } from "./UnifiedSearchResults";

const base: Omit<UnifiedItem, "store" | "id" | "citation" | "status" | "verified"> = {
  heading: "", excerpt: "Fictional words.", text_length: 16, note: "", source_name: "Invented gazette", source_url: "https://example.invalid/x", version: "invented", commencement: "", historical: false,
  date_check: null, also_in_drafts: false, open: null,
};

function render(data: UnifiedResponse, term = "hoards tokens", onDate = "") {
  const qc = new QueryClient();
  qc.setQueryData(["unified-search", term, onDate], data);
  return renderToStaticMarkup(
    <QueryClientProvider client={qc}>
      <UnifiedSearchResults term={term} onDate={onDate} />
    </QueryClientProvider>,
  );
}

const empty = { query: "", checked_on: null, notices: [], legend: {}, counts: { verified_library: 0, structured: 0, draft: 0, mapping: 0 } };

describe("unified law search results", () => {
  it("labels a verified result VERIFIED and every other kind as not reviewed, with the store named", () => {
    const html = render({
      ...empty, counts: { verified_library: 1, structured: 1, draft: 1, mapping: 1 }, notices: [], results: [
        { ...base, store: "verified_library", id: "v1", citation: "Section 3, Fictional Act", status: "VERIFIED", verified: true },
        { ...base, store: "structured", id: "s1", citation: "Section 3, Fictional Act (whole)", status: "UNVERIFIED - not reviewed", verified: false },
        { ...base, store: "draft", id: "d1", citation: "Section 3, Fictional Act (draft)", status: "UNVERIFIED - not reviewed", verified: false, also_in_drafts: true },
        { ...base, store: "mapping", id: "m1", citation: "Old 3 -> New 4", status: "UNVERIFIED - not reviewed", verified: false },
      ],
    });
    expect(html.match(/data-testid="unified-status"[^>]*>VERIFIED</g)).toHaveLength(1);
    expect(html.match(/UNVERIFIED - not reviewed/g)).toHaveLength(3);
    for (const label of ["Verified library", "Law library (whole provision)", "Draft text", "Old code to new code"]) expect(html).toContain(label);
    expect(html).toContain("1 verified, 1 law library, 1 draft text, 1 old-to-new");
    expect(html.indexOf("Verified library")).toBeLessThan(html.indexOf("Law library (whole provision)"));
  });

  it("shows the date check and a notice, and an honest empty message", () => {
    const html = render({
      ...empty, checked_on: "2023-03-12", notices: ["Nothing in the verified library matches. Every result below is unreviewed."], results: [
        { ...base, store: "draft", id: "d2", citation: "Section 7, Fictional Dated Act", status: "UNVERIFIED - not reviewed", verified: false,
          date_check: { on: "2023-03-12", state: "NOT_YET_IN_FORCE", note: "From the Act's own text." } },
      ],
    });
    expect(html).toContain("On 2023-03-12: not yet in force. From the Act&#x27;s own text.");
    expect(html).toContain("Every result below is unreviewed.");
    const none = render({ ...empty, results: [] });
    expect(none).toContain('data-testid="unified-empty"');
  });

  it("renders nothing until something is typed", () => {
    expect(render({ ...empty, results: [] }, "")).toBe("");
  });
});
