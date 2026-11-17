import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import { formatDate, formatMoney } from "@/lib/format";
import type { InterestResult, LimitationResult, RecoveryCase } from "@/lib/types";

/**
 * Interest to date (pure arithmetic on the owner's own rate) and the time-limit warning.
 * The warning shows a deadline ONLY where a lawyer-verified rule exists; otherwise it is deliberately generic.
 */
export default function InterestLimitationCard({ c, caseId }: { c: RecoveryCase; caseId: string }) {
  const hasInterestInputs = !!c.due_date && c.interest_rate_pct != null;

  const interest = useQuery<InterestResult>({
    queryKey: ["recovery-interest", caseId, c.due_date, c.interest_rate_pct, c.paid_amount, c.detected_amount, c.amount],
    queryFn: () => apiGet<InterestResult>(`/recovery/cases/${caseId}/interest`),
    enabled: hasInterestInputs,
  });
  const limitation = useQuery<LimitationResult>({
    queryKey: ["recovery-limitation", caseId, c.due_date],
    queryFn: () => apiGet<LimitationResult>(`/recovery/cases/${caseId}/limitation`),
  });

  const lim = limitation.data;
  const i = interest.data;

  return (
    <div className="rounded-md border border-border p-4" data-testid="interest-limitation">
      <div data-testid="limitation-warning">
        <p className="text-sm">Time limits</p>
        {lim?.mode === "NEEDS_DUE_DATE" && (
          <p className="mt-1 text-xs text-muted-foreground">{lim.message}</p>
        )}
        {lim && lim.mode !== "NEEDS_DUE_DATE" && (
          <>
            <p className="mt-1 text-xs" style={{ color: "#F0A63A" }}>
              This debt fell due {lim.age_text} ago.
            </p>
            <p className="mt-1 text-xs text-muted-foreground">{lim.message}</p>
            {lim.rules.map((r) => (
              <div key={r.id} className="mt-2 rounded border border-border p-2 text-xs" data-testid="limitation-rule">
                <p>
                  If your claim is: <span className="text-muted-foreground">{r.applies_to}</span>
                </p>
                <p className="mt-1" style={{ color: r.status === "PASSED" ? "#E0604D" : r.status === "SOON" ? "#F0A63A" : "#5B8CFF" }}>
                  {r.status === "PASSED"
                    ? `The ${r.period_years}-year period ended on ${formatDate(r.deadline)}.`
                    : `The ${r.period_years}-year period ends on ${formatDate(r.deadline)} (${r.days_left} days left).`}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Source: {r.citation} — “{r.source_text}” Verified by {r.verified_by} on {formatDate(r.verified_on)}.
                </p>
              </div>
            ))}
          </>
        )}
      </div>

      <div className="mt-4 border-t border-border/50 pt-3" data-testid="interest-panel">
        <p className="text-sm">Interest to date</p>
        {!hasInterestInputs && (
          <p className="mt-1 text-xs text-muted-foreground">
            Add the due date and an interest rate in “Details for your notice” to see interest worked out. No interest
            is claimed unless you do.
          </p>
        )}
        {hasInterestInputs && interest.isLoading && <div className="mt-2 h-8 rounded vidhi-sweep" />}
        {i && (
          <div className="mt-2 text-sm">
            <div className="flex flex-wrap gap-x-5 gap-y-1">
              <span data-testid="interest-amount" style={{ color: "#C8A96B" }}>
                Interest: {formatMoney(i.interest, i.currency)}
              </span>
              <span>Still owed (before interest): {formatMoney(i.principal_remaining, i.currency)}</span>
              <span data-testid="interest-total">Total to claim: {formatMoney(i.total_due, i.currency)}</span>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              {i.rate_pct}% a year, simple interest, {formatDate(i.start)} to {formatDate(i.as_of)} ({i.days} days).
            </p>
            <details className="mt-2 text-xs">
              <summary className="cursor-pointer text-muted-foreground">Show the working</summary>
              <table className="mt-2 w-full text-left text-xs">
                <thead className="text-muted-foreground">
                  <tr>
                    <th className="py-1 pr-2 font-normal">From</th>
                    <th className="py-1 pr-2 font-normal">To</th>
                    <th className="py-1 pr-2 font-normal">Days</th>
                    <th className="py-1 pr-2 font-normal">Owed</th>
                    <th className="py-1 font-normal">Interest</th>
                  </tr>
                </thead>
                <tbody>
                  {i.segments.map((s) => (
                    <tr key={s.from} className="border-t border-border/40">
                      <td className="py-1 pr-2">{formatDate(s.from)}</td>
                      <td className="py-1 pr-2">{formatDate(s.to)}</td>
                      <td className="py-1 pr-2">{s.days}</td>
                      <td className="py-1 pr-2">{formatMoney(s.balance, i.currency)}</td>
                      <td className="py-1">{formatMoney(s.interest, i.currency)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <ul className="mt-2 list-disc space-y-0.5 pl-4 text-xs text-muted-foreground">
                {i.assumptions.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            </details>
          </div>
        )}
      </div>
    </div>
  );
}
