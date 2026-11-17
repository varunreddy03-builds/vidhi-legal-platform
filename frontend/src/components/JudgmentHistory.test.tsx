import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import JudgmentHistory, { type JudgmentHistoryData, type JudgmentRelation } from "./JudgmentHistory";

function render(data: JudgmentHistoryData) {
  const qc = new QueryClient();
  qc.setQueryData(["judgment-history", data.judgment_id], data);
  return renderToStaticMarkup(
    <QueryClientProvider client={qc}>
      <JudgmentHistory id={data.judgment_id} />
    </QueryClientProvider>,
  );
}

const LIMIT = "This is only what has been loaded. It does not say whether the decision is good law or binds anyone; a lawyer must check the decisions themselves.";
const rel: JudgmentRelation = {
  id: "r1", relation: "overruled", label: "This judgment overrules", from_id: "j1", target_ref: "Alpha Traders v. Beta Mills", target_id: null, quote: "We overrule the view expressed in Alpha Traders v. Beta Mills (supra).",
  source: "stated in the judgment's own text", status: "UNVERIFIED - not reviewed", verified: false, reviewed_by: null, reviewed_on: null, note: "Not reviewed: found by fixed rules in the judgment's text and not compared with it by a person.",
};

describe("judgment history", () => {
  it("says Not known when no source states anything, and never claims the judgment is good law", () => {
    const html = render({ judgment_id: "j0", stated_in_this_judgment: [], stated_by_later_judgments: [], known: false, limit: LIMIT, message: "Not known: no source in VIDHI states what happened to this judgment." });
    expect(html).toContain("Not known: no source in VIDHI states what happened to this judgment.");
    expect(html).toContain('data-testid="judgment-history-unknown"');
    expect(html).not.toContain("judgment-relation");
    expect(html.replace(LIMIT, "").toLowerCase()).not.toContain("good law");
  });

  it("shows a stated relation with its sentence, its source and an unreviewed badge; a reviewed one names the reviewer", () => {
    const html = render({ judgment_id: "j1", known: true, limit: LIMIT, stated_by_later_judgments: [], stated_in_this_judgment: [rel, { ...rel, id: "r2", status: "REVIEWED", verified: true, reviewed_by: "Adv Invented Reviewer", reviewed_on: "2026-11-03" }] });
    expect(html).toContain("This judgment overrules");
    expect(html).toContain("Alpha Traders v. Beta Mills");
    expect(html).toContain("We overrule the view expressed in Alpha Traders v. Beta Mills (supra).");
    expect(html).toContain("Source: stated in the judgment&#x27;s own text");
    expect(html).toContain("UNVERIFIED - not reviewed");
    expect(html).toContain("Reviewed by Adv Invented Reviewer on 2026-11-03");
    expect(html).not.toContain("judgment-history-unknown");
  });
});
