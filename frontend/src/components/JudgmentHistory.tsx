import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";

export interface JudgmentRelation {
  id: string;
  relation: string;
  label: string;
  from_id: string;
  target_ref: string;
  target_id: string | null;
  quote: string;
  source: string;
  status: string;
  verified: boolean;
  reviewed_by: string | null;
  reviewed_on: string | null;
  source_url?: string;
  note: string;
}

export interface JudgmentHistoryData {
  judgment_id: string;
  stated_in_this_judgment: JudgmentRelation[];
  stated_by_later_judgments: JudgmentRelation[];
  known: boolean;
  limit: string;
  message?: string;
}

function Row({ r }: { r: JudgmentRelation }) {
  const colour = r.verified ? "#4CAF7A" : "#F0A63A";
  return (
    <li className="rounded border border-border p-2" data-testid="judgment-relation">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">{r.label}</span>
        {r.target_ref && <span className="text-sm">{r.target_ref}</span>}
        <span className="rounded-full border px-2 py-0.5 text-[11px]" style={{ color: colour, borderColor: colour }} data-testid="judgment-relation-status">
          {r.verified ? `Reviewed by ${r.reviewed_by} on ${r.reviewed_on}` : r.status}
        </span>
      </div>
      <p className="mt-1 whitespace-pre-line text-xs italic">“{r.quote}”</p>
      <p className="mt-1 text-xs text-muted-foreground">
        Source: {r.source}. {r.note}
      </p>
    </li>
  );
}

/** What is recorded about a judgment's appeals and later treatment. Only what a source states is shown; when nothing is recorded it says so. It never says whether a judgment is still good law. */
export default function JudgmentHistory({ id }: { id: string }) {
  const q = useQuery<JudgmentHistoryData>({ queryKey: ["judgment-history", id], queryFn: () => apiGet(`/judgments/${encodeURIComponent(id)}/history`) });
  if (q.isLoading) return <p className="mt-2 text-sm text-muted-foreground">Looking up what is recorded…</p>;
  if (q.isError || !q.data) return <p className="mt-2 text-sm text-muted-foreground">The history could not be loaded. Try again.</p>;
  const d = q.data;
  return (
    <section className="mt-2 space-y-2" data-testid="judgment-history" aria-label="Appeals and later treatment">
      {!d.known && (
        <p className="text-sm" data-testid="judgment-history-unknown">
          {d.message}
        </p>
      )}
      {d.stated_in_this_judgment.length > 0 && (
        <div>
          <p className="text-xs uppercase tracking-wider text-muted-foreground">Stated in this judgment</p>
          <ul className="mt-1 space-y-2">
            {d.stated_in_this_judgment.map((r) => (
              <Row key={r.id} r={r} />
            ))}
          </ul>
        </div>
      )}
      {d.stated_by_later_judgments.length > 0 && (
        <div>
          <p className="text-xs uppercase tracking-wider text-muted-foreground">Stated by later judgments</p>
          <ul className="mt-1 space-y-2">
            {d.stated_by_later_judgments.map((r) => (
              <Row key={r.id} r={r} />
            ))}
          </ul>
        </div>
      )}
      <p className="text-xs text-muted-foreground">{d.limit}</p>
    </section>
  );
}
