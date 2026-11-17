import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

type Day = { day: string; calls: number; failed: number; cost_inr: number; by_provider: Record<string, number> };
interface Weekly {
  generated_at: string;
  ai_cost_by_day: Day[];
  ai_errors_7d: { failed: number; calls: number; failure_rate_pct: number; top: { provider: string; task: string; error: string; count: number }[] };
  wrong_results_7d: { answers_marked_down: number; answers_marked_up: number; results_marked_wrong: number; wrong_by_kind: { kind: string; count: number }[]; all_time: { answers_marked_down: number; results_marked_wrong: number } };
  library_review: { sections_total: number; reviewed: number; rejected: number; waiting: number; reviewed_percent: number; reviewed_or_rejected_last_7_days: number; library_entries_verified: number; candidates_waiting: number };
  pilot_accounts: { organisation: string; started: string | null; members: number; matters: number; last_seen: string | null; ai_calls_7d: number; ai_cost_7d_inr: number; marked_down_7d: number }[];
}

const rupees = (n: number) => `₹${n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

function Block({ id, title, note, children }: { id: string; title: string; note?: string; children: React.ReactNode }) {
  return (
    <section className="glass rounded-lg p-4" data-testid={`weekly-${id}`} aria-labelledby={`weekly-${id}-h`}>
      <h2 id={`weekly-${id}-h`} className="font-heading text-xs uppercase tracking-wider text-muted-foreground">{title}</h2>
      {note && <p className="mt-1 text-xs text-muted-foreground">{note}</p>}
      <div className="mt-3 text-sm">{children}</div>
    </section>
  );
}

/** The operator's weekly look: AI cost by day, AI errors, wrong-result reports, how far the law library review has got, and the pilot accounts. Counts and names only. */
export default function WeeklyView() {
  const q = useQuery({ queryKey: ["admin-weekly"], queryFn: () => apiGet<Weekly>("/admin/weekly?days=14") });
  if (q.isPending) return <p className="text-sm text-muted-foreground" role="status">Loading this week…</p>;
  if (q.isError || !q.data) return <p className="text-sm" role="alert" style={{ color: "#F0A63A" }}>The weekly view could not be loaded. Reload the page; if it keeps failing, look at the error tracker.</p>;
  const w = q.data;
  const maxCost = Math.max(...w.ai_cost_by_day.map((d) => d.cost_inr), 0.01);
  const total = w.ai_cost_by_day.reduce((s, d) => s + d.cost_inr, 0);
  const lib = w.library_review;
  return (
    <div className="space-y-4" data-testid="admin-weekly">
      <p className="text-xs text-muted-foreground">As of {formatDateTime(w.generated_at)}. Counts and names only: nothing anyone wrote, and nothing from a matter.</p>

      <Block id="cost" title="AI cost by day" note={`Last ${w.ai_cost_by_day.length} days (Indian days). Total ${rupees(total)}. A failed call costs nothing but is counted.`}>
        <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="AI cost by day (scrolls sideways on a small screen)">
          <table className="w-full text-left text-xs">
            <thead className="text-muted-foreground"><tr><th className="py-1 pr-3">Day</th><th className="pr-3">Calls</th><th className="pr-3">Failed</th><th className="pr-3">Cost</th><th className="pr-3">Share of the busiest day</th><th>By provider</th></tr></thead>
            <tbody>
              {w.ai_cost_by_day.map((d) => (
                <tr key={d.day} className="border-t border-border align-top" data-testid="weekly-cost-row">
                  <td className="py-1 pr-3 whitespace-nowrap">{d.day}</td>
                  <td className="pr-3">{d.calls}</td>
                  <td className="pr-3">{d.failed}</td>
                  <td className="pr-3 whitespace-nowrap">{rupees(d.cost_inr)}</td>
                  <td className="pr-3"><span className="block h-2 rounded bg-primary/60" style={{ width: `${Math.round((100 * d.cost_inr) / maxCost)}%`, minWidth: d.cost_inr > 0 ? 2 : 0 }} aria-hidden="true" /></td>
                  <td>{Object.entries(d.by_provider).map(([p, c]) => `${p} ${rupees(c)}`).join(", ") || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Block>

      <Block id="errors" title="AI errors, last 7 days" note="Which provider and which kind of error. The provider's own message is never kept.">
        <p data-testid="weekly-error-rate">{w.ai_errors_7d.failed} of {w.ai_errors_7d.calls} calls failed ({w.ai_errors_7d.failure_rate_pct}%).</p>
        {w.ai_errors_7d.top.length === 0 ? <p className="mt-1 text-muted-foreground">No failed calls recorded.</p> : (
          <ul className="mt-2 list-disc space-y-0.5 pl-5 text-xs">{w.ai_errors_7d.top.map((e) => <li key={`${e.provider}${e.task}${e.error}`}>{e.provider}, {e.task}: {e.error} ({e.count})</li>)}</ul>
        )}
      </Block>

      <Block id="wrong" title="Reports that a result was wrong, last 7 days" note="Counts for every organisation. The wording of a comment stays on the Pilot tab (pilot organisations only).">
        <p data-testid="weekly-wrong-counts">Answers marked down: {w.wrong_results_7d.answers_marked_down} (marked up: {w.wrong_results_7d.answers_marked_up}). Katalyst results marked wrong: {w.wrong_results_7d.results_marked_wrong}. All time: {w.wrong_results_7d.all_time.answers_marked_down} answers marked down, {w.wrong_results_7d.all_time.results_marked_wrong} results marked wrong.</p>
        {w.wrong_results_7d.wrong_by_kind.length > 0 && <ul className="mt-2 list-disc pl-5 text-xs">{w.wrong_results_7d.wrong_by_kind.map((k) => <li key={k.kind}>{k.kind}: {k.count}</li>)}</ul>}
      </Block>

      <Block id="library" title="Law library review" note="Sections compared with the official text by a named person. Loaded is not reviewed.">
        <p data-testid="weekly-library-counts">{lib.reviewed} of {lib.sections_total} sections reviewed ({lib.reviewed_percent}%); {lib.rejected} rejected; {lib.waiting} waiting. {lib.reviewed_or_rejected_last_7_days} reviewed or rejected in the last 7 days. {lib.library_entries_verified} entries in the verified library; {lib.candidates_waiting} candidates waiting.</p>
        <div className="mt-2 h-2 w-full max-w-md overflow-hidden rounded bg-muted" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(lib.reviewed_percent)} aria-label="Share of sections reviewed">
          <div className="h-full bg-primary" style={{ width: `${lib.reviewed_percent}%` }} />
        </div>
      </Block>

      <Block id="pilot" title="Pilot accounts" note="Each pilot organisation: use over the last 7 days and when it was last seen.">
        {w.pilot_accounts.length === 0 ? <p className="text-muted-foreground">No pilot accounts yet.</p> : (
          <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Pilot accounts (scrolls sideways on a small screen)">
            <table className="w-full text-left text-xs">
              <thead className="text-muted-foreground"><tr><th className="py-1 pr-3">Organisation</th><th className="pr-3">Members</th><th className="pr-3">Matters</th><th className="pr-3">Last seen</th><th className="pr-3">AI calls</th><th className="pr-3">AI cost</th><th>Marked down</th></tr></thead>
              <tbody>
                {w.pilot_accounts.map((p) => (
                  <tr key={p.organisation + p.started} className="border-t border-border" data-testid="weekly-pilot-row">
                    <td className="py-1 pr-3">{p.organisation}</td><td className="pr-3">{p.members}</td><td className="pr-3">{p.matters}</td>
                    <td className="pr-3 whitespace-nowrap">{p.last_seen ? formatDateTime(p.last_seen) : "never"}</td><td className="pr-3">{p.ai_calls_7d}</td><td className="pr-3 whitespace-nowrap">{rupees(p.ai_cost_7d_inr)}</td><td>{p.marked_down_7d}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Block>
    </div>
  );
}
