import { Badge } from "@/components/ui/badge";
import type { DocumentAnalysis } from "@/lib/types";

function Quote({ text, verified }: { text: string; verified: boolean | null }) {
  if (!text) return null;
  return (
    <p className="mt-1 text-xs text-muted-foreground">
      “{text}”{" "}
      {verified === false && (
        <span style={{ color: "#F0A63A" }} data-testid="quote-not-found">
          — this quote was not found in the document; treat with caution
        </span>
      )}
    </p>
  );
}

/** Shows an analysis according to what the document is: clause flags for contracts, facts/people/anomalies for evidence. */
export default function AnalysisView({ a }: { a: DocumentAnalysis }) {
  const isContract = a.doc_class === "CONTRACT";
  return (
    <div className="mt-4 border-t border-border pt-3" data-testid="document-analysis">
      <p className="text-sm">{a.summary}</p>
      {a.coverage_note && <p className="mt-1 text-xs" style={{ color: "#F0A63A" }}>{a.coverage_note}</p>}

      {isContract &&
        a.flags.map((f, i) => (
          <div key={i} className="mt-3 rounded border border-border p-3">
            <div className="flex items-center gap-2">
              <Badge variant={f.risk === "HIGH" ? "destructive" : "outline"}>{f.risk}</Badge>
              <span className="text-xs text-muted-foreground">{f.page ? `page ${f.page}` : "page unknown"}</span>
            </div>
            <p className="mt-1.5 text-sm">{f.clause}</p>
            <p className="mt-1 text-xs text-muted-foreground">{f.why}</p>
            <Quote text={f.quote} verified={f.quote_verified} />
          </div>
        ))}

      {!isContract && (
        <>
          {a.key_facts.length > 0 && (
            <div className="mt-3" data-testid="analysis-facts">
              <p className="text-xs uppercase tracking-wider text-muted-foreground">Key facts</p>
              {a.key_facts.map((f, i) => (
                <div key={i} className="mt-2 rounded border border-border p-3">
                  <p className="text-sm">{f.fact}</p>
                  <p className="text-xs text-muted-foreground">{f.page ? `page ${f.page}` : "page unknown"}</p>
                  <Quote text={f.quote} verified={f.quote_verified} />
                </div>
              ))}
            </div>
          )}
          {a.people.length > 0 && (
            <div className="mt-3" data-testid="analysis-people">
              <p className="text-xs uppercase tracking-wider text-muted-foreground">People named</p>
              <ul className="mt-1.5 space-y-1 text-sm">
                {a.people.map((p, i) => (
                  <li key={i}>
                    {p.name} <span className="text-muted-foreground">— {p.role}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {a.anomalies.length > 0 && (
            <div className="mt-3" data-testid="analysis-anomalies">
              <p className="text-xs uppercase tracking-wider" style={{ color: "#F0A63A" }}>
                Differences / things to check
              </p>
              {a.anomalies.map((x, i) => (
                <div key={i} className="mt-2 rounded border p-3" style={{ borderColor: "#F0A63A44" }}>
                  <p className="text-sm">{x.what}</p>
                  <Quote text={x.quote} verified={x.quote_verified} />
                </div>
              ))}
            </div>
          )}
          {a.evidence_items_found > 0 && (
            <p className="mt-3 text-xs" style={{ color: "#5B8CFF" }} data-testid="analysis-evidence-count">
              {a.evidence_items_found} evidence item{a.evidence_items_found === 1 ? "" : "s"} added to the Evidence tab
              (each one quoted from this document).
            </p>
          )}
        </>
      )}
      {a.unclear.length > 0 && (
        <p className="mt-3 text-xs text-muted-foreground">Unclear in the document: {a.unclear.join("; ")}</p>
      )}
      {a.neutral_adjusted && (
        <p className="mt-2 text-xs text-muted-foreground">
          Wording that judged a person&apos;s honesty was removed — VIDHI flags differences; lawyers decide.
        </p>
      )}
      <p className="mt-3 text-xs text-muted-foreground">{a.disclaimer}</p>
    </div>
  );
}
