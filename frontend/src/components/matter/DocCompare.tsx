import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { apiPost } from "@/lib/api";
import { describe } from "@/lib/interaction";
import type { DocumentOut } from "@/lib/types";

type Segment = { op: "equal" | "insert" | "delete"; text: string };
type Result = {
  first: { id: string; filename: string };
  second: { id: string; filename: string };
  warnings: string[];
  segments: Segment[];
  counts: { added_words: number; deleted_words: number; unchanged_words: number };
  identical: boolean;
};

const SELECT = "h-8 min-w-0 flex-1 rounded-lg border border-input bg-transparent px-2 text-xs outline-none focus-visible:border-ring dark:bg-input/30";

/** Compare two documents of the matter: what is added, deleted or changed, word by word, on the text VIDHI read. Changes are shown with a mark and a word as well as a colour. */
export default function DocCompare({ docs }: { docs: DocumentOut[] }) {
  const readable = docs.filter((d) => d.text_available);
  const [first, setFirst] = useState("");
  const [second, setSecond] = useState("");
  const run = useMutation({
    mutationFn: () => apiPost<Result>("/documents/compare", { first_id: first, second_id: second }),
    onError: (e) => toast.error(describe(e)),
  });
  if (readable.length < 2) return null;
  const r = run.data;
  return (
    <section className="rounded-xl border p-3" aria-label="Compare two documents" data-testid="doc-compare">
      <h3 className="text-sm font-medium">Compare two documents</h3>
      <p className="mt-0.5 text-xs text-muted-foreground">Shows what was added, deleted or changed between two versions, on the text VIDHI read. Nothing is changed.</p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <select value={first} onChange={(e) => setFirst(e.target.value)} aria-label="First (older) document" className={SELECT} data-testid="compare-first">
          <option value="">First (older) document…</option>
          {readable.map((d) => (
            <option key={d.id} value={d.id} className="bg-popover">
              {d.filename}
            </option>
          ))}
        </select>
        <select value={second} onChange={(e) => setSecond(e.target.value)} aria-label="Second (newer) document" className={SELECT} data-testid="compare-second">
          <option value="">Second (newer) document…</option>
          {readable.map((d) => (
            <option key={d.id} value={d.id} className="bg-popover">
              {d.filename}
            </option>
          ))}
        </select>
        <Button size="sm" variant="outline" disabled={!first || !second || first === second || run.isPending} onClick={() => run.mutate()} data-testid="compare-run">
          {run.isPending ? "Comparing…" : "Compare"}
        </Button>
      </div>
      {first && first === second && <p className="mt-1 text-xs text-muted-foreground">Choose two different documents.</p>}
      {r && (
        <div className="mt-3" data-testid="compare-result">
          <p className="text-xs" aria-live="polite">
            {r.identical ? "The text of the two documents is identical." : `${r.counts.added_words} words added, ${r.counts.deleted_words} words deleted, ${r.counts.unchanged_words} unchanged.`}
          </p>
          {r.warnings.map((w) => (
            <p key={w} className="mt-1 text-xs" style={{ color: "#F0A63A" }}>
              {w}
            </p>
          ))}
          {!r.identical && (
            <>
              <p className="mt-2 text-xs text-muted-foreground">
                <ins className="bg-emerald-500/20 no-underline">[+ added]</ins> only in {r.second.filename} · <del className="bg-red-500/20">[− deleted]</del> only in {r.first.filename}
              </p>
              <div className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap rounded-lg border bg-muted/20 p-3 text-sm leading-relaxed" tabIndex={0} role="region" aria-label="Comparison of the two documents">
                {r.segments.map((s, i) =>
                  s.op === "equal" ? (
                    <span key={i}>{s.text}</span>
                  ) : s.op === "insert" ? (
                    <ins key={i} className="rounded-sm bg-emerald-500/25 no-underline" data-testid="compare-added">
                      <span className="sr-only">[added: </span>
                      {s.text}
                      <span className="sr-only">]</span>
                    </ins>
                  ) : (
                    <del key={i} className="rounded-sm bg-red-500/25" data-testid="compare-deleted">
                      <span className="sr-only">[deleted: </span>
                      {s.text}
                      <span className="sr-only">]</span>
                    </del>
                  ),
                )}
              </div>
            </>
          )}
        </div>
      )}
    </section>
  );
}
