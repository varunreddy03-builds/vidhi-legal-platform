import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { apiGet } from "@/lib/api";
import type { JudgmentEntry } from "@/lib/types";
import JudgmentHistory from "@/components/JudgmentHistory";

/** One High Court judgment: always "not reviewed". The full text loads only when the person asks for it. */
export function JudgmentCard({ j }: { j: JudgmentEntry }) {
  const [open, setOpen] = useState(false);
  const [history, setHistory] = useState(false);
  const full = useQuery<{ text: string; text_error?: string; text_kind?: string }>({ queryKey: ["judgment", j.id], queryFn: () => apiGet(`/judgments/${encodeURIComponent(j.id)}`), enabled: open });
  const more = j.text_kind === "NOT_LOADED" || j.text_chars > j.excerpt.length;
  return (
    <li className="rounded-md border border-border p-3" data-testid="judgment-item">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">{j.case_title ?? j.cnr ?? j.id}</span>
        <span className="rounded-full border px-2 py-0.5 text-[11px]" style={{ color: "#F0A63A", borderColor: "#F0A63A" }} data-testid="judgment-badge">
          Not reviewed
        </span>
        {j.text_kind === "OCR" && <span className="rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground">Read by OCR: may contain mistakes</span>}
        {j.text_kind === "UNREADABLE" && <span className="rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground">The court file could not be opened</span>}
      </div>
      <p className="mt-1 text-xs text-muted-foreground">
        {j.court_name}
        {j.decision_date ? ` · decided ${j.decision_date}` : ""}
        {j.judge ? ` · ${j.judge}` : ""}
        {j.disposal ? ` · ${j.disposal}` : ""}
      </p>
      {j.citation && <p className="mt-1 text-xs text-muted-foreground">{j.citation}</p>}
      {open && full.isLoading && <p className="mt-2 text-sm text-muted-foreground">Fetching the judgment from the public archive…</p>}
      {open && full.data && !full.data.text && (
        <p className="mt-2 text-sm text-muted-foreground" data-testid="judgment-no-text">
          {full.data.text_error ?? "This court file has no readable text (it may be a scan). Open the court PDF with the link."}
        </p>
      )}
      {(j.excerpt || (open && full.data?.text)) && (
        <p className="mt-2 whitespace-pre-line text-sm">
          {open && full.data?.text ? full.data.text : j.excerpt}
          {!open && more ? " …" : ""}
        </p>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        {more && (
          <button type="button" className="underline underline-offset-2" onClick={() => setOpen((v) => !v)} data-testid="judgment-toggle">
            {open ? "Show less" : "Show the whole text"}
          </button>
        )}
        <button type="button" className="underline underline-offset-2" onClick={() => setHistory((v) => !v)} aria-expanded={history} data-testid="judgment-history-toggle">
          {history ? "Hide appeals and later treatment" : "Appeals and later treatment"}
        </button>
        {j.cnr && <span>CNR {j.cnr}</span>}
        <a href={j.source_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 underline underline-offset-2">
          Court PDF <ExternalLink className="size-3" />
        </a>
      </div>
      {history && <JudgmentHistory id={j.id} />}
    </li>
  );
}

/** Judgments that look relevant to an answer: found by search, never used to verify a claim. */
export default function Judgments({ items }: { items: JudgmentEntry[] }) {
  if (!items.length) return null;
  return (
    <section data-testid="judgments" aria-label="Possibly relevant High Court judgments, not reviewed">
      <p className="text-xs uppercase tracking-wider text-muted-foreground">Possibly relevant High Court judgments (not reviewed)</p>
      <p className="mt-1 text-xs text-muted-foreground">
        Found by search in the public High Court dataset. Nobody has compared them with the court&apos;s own copy, and they may have been appealed or set aside. Nothing above rests on them.
      </p>
      <ul className="mt-2 space-y-2">
        {items.map((j) => (
          <JudgmentCard key={j.id} j={j} />
        ))}
      </ul>
    </section>
  );
}
