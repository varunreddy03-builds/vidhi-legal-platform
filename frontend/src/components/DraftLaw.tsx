import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { apiGet } from "@/lib/api";
import type { DraftLawEntry } from "@/lib/types";

/** One draft provision: always labelled "not reviewed". The full text loads only when the person asks for it. */
export function DraftLawCard({ d }: { d: DraftLawEntry }) {
  const [open, setOpen] = useState(false);
  const full = useQuery<{ text: string; text_sha256: string; oversized: boolean }>({
    queryKey: ["draft-law", d.id],
    queryFn: () => apiGet(`/library/drafts/${encodeURIComponent(d.id)}`),
    enabled: open,
  });
  return (
    <li className="rounded-md border border-border p-3" data-testid="draft-law-item">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">{d.citation}</span>
        <span className="rounded-full border px-2 py-0.5 text-[11px]" style={{ color: "#F0A63A", borderColor: "#F0A63A" }} data-testid="draft-law-badge">
          Not reviewed
        </span>
        {d.historical && (
          <span className="rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground" data-testid="draft-law-historical">
            Repealed: applies only to what happened while it was in force
          </span>
        )}
      </div>
      {d.in_force_on_date && (
        <p className="mt-1 text-xs" style={{ color: d.in_force_on_date === "IN_FORCE" ? "#4CAF7A" : d.in_force_on_date === "UNKNOWN" ? undefined : "#F0A63A" }} data-testid="draft-law-date-check">
          On {d.checked_on}: {d.in_force_on_date === "IN_FORCE" ? "in force" : d.in_force_on_date === "NOT_YET_IN_FORCE" ? "not yet in force" : d.in_force_on_date === "PART_IN_FORCE" ? "partly in force (starts in stages)" : d.in_force_on_date === "REPEALED" ? "already repealed" : "dates not stated"}. {d.date_note}
        </p>
      )}
      {d.text_source === "OCR" && (
        <p className="mt-1 text-xs text-muted-foreground" data-testid="draft-law-ocr">
          Read from a scanned PDF by OCR: words may run together and letters may be wrong. {d.coverage_note}
        </p>
      )}
      {d.heading && <p className="mt-1 text-xs text-muted-foreground">{d.heading}</p>}
      <p className="mt-2 whitespace-pre-line text-sm">{open && full.data ? full.data.text : d.excerpt}{!open && d.text_length > d.excerpt.length ? " …" : ""}</p>
      {open && full.data?.oversized && (
        <p className="mt-1 text-xs text-muted-foreground">This entry is very long: the Act's last section may run on into its Schedules. A lawyer must cut it at the real end.</p>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        {d.text_length > d.excerpt.length && (
          <button type="button" className="underline underline-offset-2" onClick={() => setOpen((v) => !v)} data-testid="draft-law-toggle">
            {open ? "Show less" : "Show the whole text"}
          </button>
        )}
        <span>{d.version}</span>
        {d.commencement && <span>{d.commencement}</span>}
        {d.source_url && (
          <a href={d.source_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 underline underline-offset-2">
            Official source <ExternalLink className="size-3" />
          </a>
        )}
      </div>
    </li>
  );
}

/** Draft provisions that look relevant to an answer: found by search, never used to verify a claim. */
export default function DraftLaw({ items }: { items: DraftLawEntry[] }) {
  if (!items.length) return null;
  return (
    <section data-testid="draft-law" aria-label="Possibly relevant law, not reviewed">
      <p className="text-xs uppercase tracking-wider text-muted-foreground">Possibly relevant law (not reviewed)</p>
      <p className="mt-1 text-xs text-muted-foreground">
        Found by search in the official texts. No lawyer has compared this wording with the source yet, so nothing above rests on it. Read the official source before relying on it.
      </p>
      <ul className="mt-2 space-y-2">
        {items.map((d) => (
          <DraftLawCard key={d.id} d={d} />
        ))}
      </ul>
    </section>
  );
}
