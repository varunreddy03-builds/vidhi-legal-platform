import { useEffect, useState } from "react";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import type { Claim, Citation } from "@/lib/types";
import { PLAIN_CLAIM_STATUS, TONE_COLOR } from "@/lib/plain";

function useNarrow() {
  const [narrow, setNarrow] = useState(() => typeof window !== "undefined" && window.matchMedia?.("(max-width: 767px)").matches);
  useEffect(() => {
    const mq = window.matchMedia?.("(max-width: 767px)");
    if (!mq) return;
    const on = () => setNarrow(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return narrow;
}

/** The source text with the exact quoted words marked, when the quote is found in it. Plain text: nothing is rewritten. */
function Passage({ c }: { c: Citation }) {
  const text = c.source_text || c.passage;
  if (!text) return <p className="text-xs text-muted-foreground">No passage was given for this source.</p>;
  const at = c.quote_verified && c.passage && c.source_text ? c.source_text.indexOf(c.passage) : -1;
  if (at < 0) return <p className="whitespace-pre-wrap rounded-lg border p-2 text-sm">{c.source_text ? text.slice(0, 1500) : `“${text}”`}</p>;
  const start = Math.max(0, at - 300);
  const end = Math.min(text.length, at + c.passage.length + 300);
  return (
    <p className="whitespace-pre-wrap rounded-lg border p-2 text-sm">
      {start > 0 ? "… " : ""}
      {text.slice(start, at)}
      <mark className="rounded-sm bg-yellow-300/50 px-0.5 text-inherit" data-testid="citation-mark">
        {text.slice(at, at + c.passage.length)}
      </mark>
      {text.slice(at + c.passage.length, end)}
      {end < text.length ? " …" : ""}
    </p>
  );
}

/** Numbered chips under an answer. A chip opens the claim's sources beside the answer (a sheet from the bottom on a phone): who published the text, which version, who compared it with the
 * source, the link, and the passage with the checked words marked. Labels are the plain ones used everywhere else; nothing here can raise a claim's status. */
export default function CitationPanel({ claims }: { claims: Claim[] }) {
  const [open, setOpen] = useState<number | null>(null);
  const narrow = useNarrow();
  const claim = open !== null ? claims[open] : null;
  const s = claim ? (PLAIN_CLAIM_STATUS[claim.verification_status] ?? PLAIN_CLAIM_STATUS.UNSUPPORTED) : null;
  return (
    <>
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Sources for each point" data-testid="citation-chips">
        <span className="text-xs text-muted-foreground">Sources:</span>
        {claims.map((c, n) => (
          <button
            key={c.id}
            type="button"
            onClick={() => setOpen(n)}
            className="rounded-full border px-2.5 py-0.5 text-xs hover:bg-muted/50 focus-visible:outline focus-visible:outline-2"
            aria-label={`Open the sources for point ${n + 1}`}
            data-testid="citation-chip"
          >
            [{n + 1}]
          </button>
        ))}
      </div>
      <Sheet open={open !== null} onOpenChange={(o) => !o && setOpen(null)}>
        <SheetContent side={narrow ? "bottom" : "right"} className={narrow ? "max-h-[85vh] overflow-auto" : "w-[min(32rem,92vw)] overflow-auto sm:max-w-none"} data-testid="citation-sheet">
          {claim && s && (
            <>
              <SheetHeader>
                <SheetTitle>Point {open! + 1}</SheetTitle>
                <SheetDescription>{claim.text}</SheetDescription>
              </SheetHeader>
              <div className="space-y-4 px-4 pb-6">
                <p className="text-xs">
                  <span className="rounded-full border px-2.5 py-0.5" style={{ color: TONE_COLOR[s.tone], borderColor: `${TONE_COLOR[s.tone]}66` }}>
                    {s.label}
                  </span>
                </p>
                {claim.citations.length === 0 && <p className="text-sm text-muted-foreground">No source was found for this point, so it could not be checked.</p>}
                {claim.citations.map((c, i) => (
                  <div key={i} className="space-y-1.5" data-testid="citation-detail">
                    <h4 className="text-sm font-medium">{c.doc_label ? `${c.doc_label}${c.page ? `, page ${c.page}` : ""}` : c.citation}</h4>
                    {c.source_name && (
                      <p className="text-xs text-muted-foreground">
                        {c.source_name}
                        {c.version ? `, version ${c.version}` : ""}
                        {c.verified_by ? `. Compared with the source by ${c.verified_by}${c.verified_on ? ` on ${c.verified_on}` : ""}.` : ""}
                      </p>
                    )}
                    {c.source_url && /^https?:\/\//.test(c.source_url) && (
                      <a href={c.source_url} target="_blank" rel="noreferrer noopener" className="text-xs underline">
                        Open the official source
                      </a>
                    )}
                    <p className="text-xs" style={{ color: c.quote_verified ? "#5B8CFF" : "#F0A63A" }}>
                      {c.quote_verified ? "The quoted words were found exactly in the source." : "The quoted words were NOT found in the source."}
                    </p>
                    <Passage c={c} />
                  </div>
                ))}
                {claim.conflicts.map((k, i) => (
                  <p key={i} className="text-xs" style={{ color: "#F5B35C" }}>
                    Another paper says something different ({k.filename}, page {k.page}): “{k.quote}”
                  </p>
                ))}
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </>
  );
}
