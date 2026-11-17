import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { apiGet } from "@/lib/api";

export interface UnifiedItem {
  store: "verified_library" | "structured" | "draft" | "mapping";
  id: string;
  citation: string;
  heading: string;
  excerpt: string;
  text_length: number;
  status: string;
  verified: boolean;
  note: string;
  source_name: string;
  source_url: string;
  version: string;
  commencement: string;
  historical: boolean;
  reading?: string;
  coverage_note?: string;
  verified_by?: string | null;
  verified_on?: string | null;
  date_check: { on: string; state: "IN_FORCE" | "NOT_YET_IN_FORCE" | "PART_IN_FORCE" | "REPEALED" | "UNKNOWN"; note: string } | null;
  also_in_drafts: boolean;
  open: { kind: "verified" | "draft"; id: string } | null;
}

export interface UnifiedResponse {
  query: string;
  checked_on: string | null;
  results: UnifiedItem[];
  counts: Record<UnifiedItem["store"], number>;
  notices: string[];
  legend: Record<string, string>;
}

const STORE_LABEL: Record<UnifiedItem["store"], string> = {
  verified_library: "Verified library",
  structured: "Law library (whole provision)",
  draft: "Draft text",
  mapping: "Old code to new code",
};
const DATE_LABEL: Record<string, string> = { IN_FORCE: "in force", NOT_YET_IN_FORCE: "not yet in force", PART_IN_FORCE: "partly in force (starts in stages)", REPEALED: "already repealed", UNKNOWN: "dates not stated" };

function Result({ r }: { r: UnifiedItem }) {
  const [open, setOpen] = useState(false);
  const full = useQuery<{ text: string }>({
    queryKey: ["unified-full", r.open?.kind, r.id],
    queryFn: () => apiGet(r.open?.kind === "verified" ? `/library/${encodeURIComponent(r.id)}` : `/library/drafts/${encodeURIComponent(r.id)}`),
    enabled: open && !!r.open,
  });
  const colour = r.verified ? "#4CAF7A" : "#F0A63A";
  return (
    <li className="rounded-md border border-border p-3" data-testid="unified-item" data-store={r.store}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">{r.citation}</span>
        <span className="rounded-full border px-2 py-0.5 text-[11px]" style={{ color: colour, borderColor: colour }} data-testid="unified-status">
          {r.status}
        </span>
        <span className="rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground" data-testid="unified-store">
          {STORE_LABEL[r.store]}
        </span>
        {r.historical && <span className="rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground">Repealed: applies only to what happened while it was in force</span>}
        {r.also_in_drafts && <span className="text-[11px] text-muted-foreground">also in the draft text</span>}
      </div>
      {r.heading && <p className="mt-1 text-xs text-muted-foreground">{r.heading}</p>}
      {r.date_check && (
        <p className="mt-1 text-xs" style={{ color: r.date_check.state === "IN_FORCE" ? "#4CAF7A" : r.date_check.state === "UNKNOWN" ? undefined : "#F0A63A" }} data-testid="unified-date">
          On {r.date_check.on}: {DATE_LABEL[r.date_check.state]}. {r.date_check.note}
        </p>
      )}
      {r.reading === "machine-read" && (
        <p className="mt-1 text-xs text-muted-foreground">Read from a scan by a machine: words may run together and letters may be wrong. {r.coverage_note}</p>
      )}
      {r.excerpt && <p className="mt-2 whitespace-pre-line text-sm">{open && full.data ? full.data.text : r.excerpt}{!open && r.text_length > r.excerpt.length ? " …" : ""}</p>}
      <p className="mt-1 text-xs text-muted-foreground">{r.note}</p>
      <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        {r.open && r.text_length > r.excerpt.length && (
          <button type="button" className="underline underline-offset-2" onClick={() => setOpen((v) => !v)}>
            {open ? "Show less" : "Show the whole text"}
          </button>
        )}
        {r.source_name && <span>{r.source_name}</span>}
        {r.version && <span>{r.version}</span>}
        {r.source_url && (
          <a href={r.source_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 underline underline-offset-2">
            Source <ExternalLink className="size-3" />
          </a>
        )}
      </div>
    </li>
  );
}

/** One search across the verified library, the law library and the draft text. Each result says where it comes from; only the verified library can say VERIFIED. */
export default function UnifiedSearchResults({ term, onDate }: { term: string; onDate: string }) {
  const q = useQuery<UnifiedResponse>({
    queryKey: ["unified-search", term, onDate],
    queryFn: () => apiGet(`/library/search?q=${encodeURIComponent(term)}&limit=10${onDate ? `&on_date=${encodeURIComponent(onDate)}` : ""}`),
    enabled: term.length > 0,
  });
  if (!term) return null;
  if (q.isLoading) return <p className="mt-4 text-sm text-muted-foreground">Searching…</p>;
  if (q.isError || !q.data) return <p className="mt-4 text-sm text-muted-foreground">The search could not be completed. Try again.</p>;
  const d = q.data;
  return (
    <section className="mt-4" data-testid="unified-results" aria-label="Search results">
      <p className="text-xs uppercase tracking-wider text-muted-foreground">
        Results: {d.counts.verified_library} verified, {d.counts.structured} law library, {d.counts.draft} draft text, {d.counts.mapping} old-to-new
      </p>
      {d.notices.map((n) => (
        <p key={n} className="mt-1 text-xs text-muted-foreground" data-testid="unified-notice">
          {n}
        </p>
      ))}
      {d.results.length === 0 ? (
        <p className="mt-2 text-sm text-muted-foreground" data-testid="unified-empty">
          Nothing found. Try other words, or a section and Act such as "section 302 IPC".
        </p>
      ) : (
        <ul className="mt-2 space-y-2" data-testid="unified-list">
          {d.results.map((r) => (
            <Result key={`${r.store}-${r.id}`} r={r} />
          ))}
        </ul>
      )}
    </section>
  );
}
